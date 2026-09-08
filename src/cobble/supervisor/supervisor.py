"""The Bedrock server supervisor (section 3).

Owns exactly one :class:`BedrockProcess` at a time, drives it through the
run-state model, and guarantees a clean shutdown path. Everything else in cobble
observes the server through this object.

Concurrency model: all state-changing methods run on the event loop and take
``_op_lock`` so only one lifecycle operation is in flight at once. Run-state
transitions additionally go through :class:`StateMachine`, whose guard rejects a
second concurrent ``start`` before any process is spawned.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cobble.acquisition.layout import Layout
from cobble.console.buffer import ConsoleBuffer
from cobble.events.patterns import is_readiness_line
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.supervisor.process import BedrockProcess
from cobble.supervisor.shutdown_record import (
    ShutdownRecord,
    load_last_shutdown,
    store_last_shutdown,
)
from cobble.supervisor.state import RunState, StateMachine, TransitionError

__all__ = [
    "AlreadyRunningError",
    "MaintenanceConflictError",
    "MaintenanceHandle",
    "MaintenanceInProgressError",
    "NoInstallationError",
    "NotRunningError",
    "ReadinessTimeoutError",
    "Supervisor",
    "SupervisorError",
    "TransitionError",
    "TransitionInProgressError",
]

log = get_logger("supervisor")

# Run states in which no server process is alive, so no configuration is "in
# effect" (server-config spec: "The server is not running → no configuration is
# recorded as being in effect").
_CONFIG_SNAPSHOT_CLEAR_STATES = frozenset(
    {
        RunState.STOPPED,
        RunState.CRASHED,
        RunState.FAILED,
        RunState.RECOVERY_ABANDONED,
    }
)


def _read_effective_config(path: Path) -> dict[str, str]:
    """The last-assignment-wins key/value map of ``server.properties`` at ``path``,
    or an empty map if it is absent or unreadable. Imported lazily to avoid an
    import cycle with :mod:`cobble.config`."""
    from cobble.config.properties import PropertiesDocument

    try:
        return PropertiesDocument.load(path).effective()
    except OSError:
        return {}


LineSink = Callable[[str], None]
StateListener = Callable[[RunState, RunState], None]
MaintenanceListener = Callable[[str | None, str | None], None]
# Fired with the wall-clock time the server is being stopped/has exited, so a
# consumer (the player roster) can close records the server will never report on
# (server-players spec; design.md D1). Both fire before the process is reaped.
StopListener = Callable[[datetime], None]
ExitListener = Callable[[datetime], None]


class SupervisorError(RuntimeError):
    """Base class for lifecycle errors, with a stable ``code``."""

    code = "supervisor_error"


class AlreadyRunningError(SupervisorError):
    code = "already_running"


class TransitionInProgressError(SupervisorError):
    code = "transition_in_progress"


class NotRunningError(SupervisorError):
    code = "not_running"


class NoInstallationError(SupervisorError):
    code = "no_installation"


class ReadinessTimeoutError(SupervisorError):
    code = "readiness_timeout"


class MaintenanceInProgressError(SupervisorError):
    """A lifecycle action was requested while a maintenance operation owns the
    server's lifecycle (server-lifecycle spec)."""

    code = "maintenance_in_progress"


class MaintenanceConflictError(SupervisorError):
    """A maintenance operation was requested while another one is already in
    progress (update state machine spec, task 6.14)."""

    code = "maintenance_conflict"


@dataclass
class ExitInfo:
    code: int | None
    crashed: bool


@dataclass
class CrashInfo:
    exit_code: int | None
    at: str  # ISO 8601 UTC of the unexpected exit


class MaintenanceHandle:
    """Passed to the body of :meth:`Supervisor.maintenance_scope`. Lets a multi-step
    operation report its current step and observe an unexpected server exit that
    happens while it owns the lifecycle."""

    def __init__(self, supervisor: Supervisor, operation: str) -> None:
        self._sup = supervisor
        self.operation = operation

    def set_step(self, step: str | None) -> None:
        self._sup._set_maintenance_step(step)

    async def wait_exit(self) -> ExitInfo:
        """Await the next unexpected exit of the managed server while this
        maintenance operation is in progress. Wrap in ``asyncio.timeout`` to
        bound the wait (e.g. a post-readiness grace window)."""
        fut = self._sup._maintenance_exit
        if fut is None:
            raise RuntimeError("maintenance is not active")
        return await asyncio.shield(fut)


class Supervisor:
    def __init__(
        self,
        settings: Settings,
        layout: Layout | None = None,
        *,
        line_sink: LineSink | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._layout = layout or Layout.from_settings(settings)
        self._sink = line_sink
        self._clock = clock

        self._sm = StateMachine(RunState.STOPPED)
        self._op_lock = asyncio.Lock()

        self._proc: BedrockProcess | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._supervise_task: asyncio.Task[None] | None = None
        self._ready_event = asyncio.Event()
        self._stop_requested = False
        self._auto_restart_enabled = True
        self._closing = False

        self._ready_at: float | None = None
        self._last_exit: ExitInfo | None = None
        self._last_crash: CrashInfo | None = None
        self._crash_times: list[float] = []

        # The effective server.properties map captured at the moment BDS was
        # spawned, held for the life of that process (server-config spec D5).
        # Pending-versus-live is derived by comparing the file on disk against
        # this, not tracked with a flag that can desynchronise.
        self._config_snapshot: dict[str, str] | None = None

        # Maintenance: a multi-step operation (update / restore / backup) that
        # owns the server's lifecycle. Orthogonal to RunState (design.md D8).
        self._maintenance: str | None = None
        self._maintenance_step: str | None = None
        self._maintenance_exit: asyncio.Future[ExitInfo] | None = None
        self._maintenance_listeners: list[MaintenanceListener] = []
        self._pre_stop_listeners: list[StopListener] = []
        self._unexpected_exit_listeners: list[ExitListener] = []

        self.console = ConsoleBuffer(settings.console_buffer_lines)
        self._last_shutdown = load_last_shutdown(settings.shutdown_record_file)

        self._state_waiters: list[tuple[frozenset[RunState], asyncio.Future[RunState]]] = []
        self._sm.subscribe(self._resolve_state_waiters)
        self._sm.subscribe(self._forget_config_snapshot_on_exit)

    def _resolve_state_waiters(self, _frm: RunState, to: RunState) -> None:
        still: list[tuple[frozenset[RunState], asyncio.Future[RunState]]] = []
        for targets, fut in self._state_waiters:
            if to in targets and not fut.done():
                fut.set_result(to)
            elif not fut.done():
                still.append((targets, fut))
        self._state_waiters = still

    def _forget_config_snapshot_on_exit(self, _frm: RunState, to: RunState) -> None:
        if to in _CONFIG_SNAPSHOT_CLEAR_STATES:
            self._config_snapshot = None

    async def wait_for_state(self, *targets: RunState) -> RunState:
        """Await the next transition into one of ``targets`` (or return now if
        already there). Wrap the call in ``asyncio.timeout`` to bound the wait.
        """
        if self._sm.state in targets:
            return self._sm.state
        fut: asyncio.Future[RunState] = asyncio.get_running_loop().create_future()
        self._state_waiters.append((frozenset(targets), fut))
        return await fut

    # -- observation --------------------------------------------------
    @property
    def state(self) -> RunState:
        return self._sm.state

    @property
    def ready_at(self) -> float | None:
        return self._ready_at if self._sm.state == RunState.RUNNING else None

    @property
    def uptime_seconds(self) -> float | None:
        if self._sm.state != RunState.RUNNING or self._ready_at is None:
            return None
        return max(0.0, self._clock() - self._ready_at)

    @property
    def last_shutdown(self) -> ShutdownRecord | None:
        return self._last_shutdown

    @property
    def last_exit(self) -> ExitInfo | None:
        return self._last_exit

    @property
    def last_crash(self) -> CrashInfo | None:
        return self._last_crash

    @property
    def config_snapshot(self) -> dict[str, str] | None:
        """The effective ``server.properties`` map the running server was started
        with, or ``None`` when the server is not running (server-config spec)."""
        if self._sm.state == RunState.RUNNING:
            return self._config_snapshot
        return None

    @property
    def maintenance(self) -> str | None:
        """The maintenance operation in progress, or ``None`` when idle."""
        return self._maintenance

    @property
    def maintenance_step(self) -> str | None:
        return self._maintenance_step

    @property
    def is_closing(self) -> bool:
        """True once :meth:`aclose` has begun — cobble itself is shutting down."""
        return self._closing

    def installed_version(self) -> str | None:
        return self._layout.installed_version()

    def subscribe_state(self, listener: StateListener) -> None:
        self._sm.subscribe(listener)

    def subscribe_maintenance(self, listener: MaintenanceListener) -> None:
        """Register a callback invoked with ``(operation, step)`` whenever a
        maintenance operation begins, advances a step, or ends."""
        self._maintenance_listeners.append(listener)

    def subscribe_pre_stop(self, listener: StopListener) -> None:
        """Register a callback fired with the stop time just before cobble stops
        a running server — for any stop path (manual, restart, maintenance,
        cobble shutdown). It runs before the process exit is reaped, so a
        consumer can close records BDS will not report on shutdown (design.md
        D1 tier 1)."""
        self._pre_stop_listeners.append(listener)

    def subscribe_unexpected_exit(self, listener: ExitListener) -> None:
        """Register a callback fired with the detection time when the server
        exits without having been asked to (design.md D1 tier 2)."""
        self._unexpected_exit_listeners.append(listener)

    def _notify_pre_stop(self) -> None:
        now = datetime.now(UTC)
        for listener in list(self._pre_stop_listeners):
            try:
                listener(now)
            except Exception:
                log.exception("pre-stop listener raised; continuing the stop")

    def _notify_unexpected_exit(self) -> None:
        now = datetime.now(UTC)
        for listener in list(self._unexpected_exit_listeners):
            try:
                listener(now)
            except Exception:
                log.exception("unexpected-exit listener raised; continuing")

    def _notify_maintenance(self) -> None:
        for listener in list(self._maintenance_listeners):
            try:
                listener(self._maintenance, self._maintenance_step)
            except Exception:
                log.exception("maintenance listener raised; continuing")

    def _set_maintenance_step(self, step: str | None) -> None:
        self._maintenance_step = step
        log.info("maintenance step: %s", step)
        self._notify_maintenance()

    def set_line_sink(self, sink: LineSink) -> None:
        self._sink = sink

    # -- maintenance interlock -----------------------------------
    @contextlib.asynccontextmanager
    async def maintenance_scope(self, operation: str) -> AsyncIterator[MaintenanceHandle]:
        """Own the server's lifecycle for a multi-step operation.

        While the block runs, ``start``/``stop``/``restart`` are rejected with
        :class:`MaintenanceInProgressError`, automatic crash restart is
        suspended, and an unexpected server exit is routed to
        :meth:`MaintenanceHandle.wait_exit` instead of triggering recovery.

        Entering fails with :class:`TransitionInProgressError` if a lifecycle
        transition is in flight, or :class:`MaintenanceConflictError` if another
        maintenance operation is already in progress.
        """
        if self._maintenance is not None:
            raise MaintenanceConflictError(
                f"a {self._maintenance} operation is already in progress"
            )
        # A lifecycle transition holds ``_op_lock`` for its whole duration.
        # Fail fast rather than queue behind it (server-lifecycle spec 2.3).
        if self._op_lock.locked() or self._sm.state in (RunState.STARTING, RunState.STOPPING):
            raise TransitionInProgressError("a lifecycle transition is in progress")
        async with self._op_lock:
            if self._maintenance is not None:
                raise MaintenanceConflictError(
                    f"a {self._maintenance} operation is already in progress"
                )
            if self._sm.state in (RunState.STARTING, RunState.STOPPING):
                raise TransitionInProgressError(
                    f"a {self._sm.state.value} transition is in progress"
                )
            self._maintenance = operation
            self._maintenance_step = None
            self._maintenance_exit = asyncio.get_running_loop().create_future()
            log.info("maintenance started: %s", operation)
            self._notify_maintenance()
        try:
            yield MaintenanceHandle(self, operation)
        finally:
            async with self._op_lock:
                fut, self._maintenance_exit = self._maintenance_exit, None
                self._maintenance = None
                self._maintenance_step = None
                # A fresh crash-restart window applies after maintenance.
                self._crash_times.clear()
                self._auto_restart_enabled = True
            if fut is not None and not fut.done():
                fut.cancel()
            log.info("maintenance ended: %s", operation)
            self._notify_maintenance()

    async def maintenance_stop(self, *, reason: str = "maintenance") -> None:
        """Clean stop issued by the maintenance operation that holds the flag.
        Bypasses the maintenance interlock; otherwise identical to :meth:`stop`."""
        async with self._op_lock:
            await self._stop_locked(reason=reason)

    async def maintenance_start(self) -> None:
        """Start issued by the maintenance operation that holds the flag.
        Bypasses the maintenance interlock; otherwise identical to :meth:`start`."""
        async with self._op_lock:
            await self._start_locked()

    def _reject_if_maintenance(self) -> None:
        """Fail fast on a lifecycle request while maintenance owns the server.

        Read without ``_op_lock``: a maintenance step (e.g. awaiting readiness of
        a new version) can hold the lock for the readiness timeout, and an
        operator's Stop/Restart must not hang that long before being rejected.
        The value only transitions under the lock, so a stale read still resolves
        to a correct ``MaintenanceInProgressError`` on the recheck below.
        """
        if self._maintenance is not None:
            raise MaintenanceInProgressError(f"a {self._maintenance} operation is in progress")

    # -- lifecycle: start ------------------------------------------
    async def start(self) -> None:
        self._reject_if_maintenance()
        async with self._op_lock:
            self._reject_if_maintenance()
            await self._start_locked()

    async def _start_locked(self) -> None:
        if self._closing:
            raise TransitionInProgressError("cobble is shutting down")
        current = self._sm.state
        if current in (RunState.STARTING, RunState.RUNNING):
            raise AlreadyRunningError("the server is already running")
        if current == RunState.STOPPING:
            raise TransitionInProgressError("a stop is in progress")
        if not self._layout.has_installation():
            raise NoInstallationError("no Bedrock installation is present")

        self._sm.transition(RunState.STARTING)
        self._auto_restart_enabled = True
        await self._spawn_and_await_ready()

    async def _spawn_and_await_ready(self) -> None:
        self._stop_requested = False
        self._ready_event = asyncio.Event()
        self._ready_at = None
        # BDS resolves server.properties, worlds/, and the vendor payload relative
        # to its working directory (design.md D2). That directory is data/: real
        # mutable state, plus symlinks to the active version's payload.
        self._layout.ensure_payload_symlinks()
        self._config_snapshot = _read_effective_config(self._layout.data_dir / "server.properties")
        run_binary = self._layout.run_binary
        # If prior output is retained, mark this process boundary so a restart is
        # distinguishable within the console history (server-console spec).
        if len(self.console) > 0:
            self.console.add_marker("— bedrock_server (re)starting —")
        self._proc = BedrockProcess(run_binary, self._layout.data_dir)
        await self._proc.start()

        self._pump_task = asyncio.create_task(self._pump_stdout(), name="cobble-stdout-pump")
        self._supervise_task = asyncio.create_task(
            self._supervise_until_exit(), name="cobble-supervise"
        )

        try:
            await asyncio.wait_for(
                self._ready_event.wait(), timeout=self._settings.readiness_timeout
            )
        except TimeoutError:
            # Readiness never signalled. Preserve captured output, then tear down.
            with contextlib.suppress(TransitionError):
                self._sm.transition(RunState.FAILED)
            await self._force_terminate(reason="readiness_timeout")
            raise ReadinessTimeoutError(
                f"server did not signal readiness within {self._settings.readiness_timeout:g}s"
            ) from None

        if self._proc is not None and not self._proc.running:
            # Exited before readiness — the supervise task will classify it.
            with contextlib.suppress(TransitionError):
                self._sm.transition(RunState.FAILED)
            raise ReadinessTimeoutError("server exited before signalling readiness")

        # Set the readiness clock before announcing RUNNING so the first pushed
        # status snapshot already carries a non-null uptime.
        self._ready_at = self._clock()
        self._sm.transition(RunState.RUNNING)
        self._persist_desired(running=True)

    async def _pump_stdout(self) -> None:
        """Always-draining stdout reader. Never blocks the child on output
        consumption (server-events spec: "Output processing does not block").
        """
        assert self._proc is not None
        try:
            async for line in self._proc.readlines():
                self.console.add_output(line)
                if self._sink is not None:
                    try:
                        self._sink(line)
                    except Exception:
                        log.exception("line sink raised; continuing")
                if not self._ready_event.is_set() and is_readiness_line(line):
                    self._ready_event.set()
        except Exception:
            log.exception("stdout pump failed")

    async def _supervise_until_exit(self) -> None:
        assert self._proc is not None
        proc = self._proc
        code = await proc.wait()
        if self._pump_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._pump_task

        requested = self._stop_requested
        self._last_exit = ExitInfo(code=code, crashed=not requested)
        log.info("bedrock_server exited code=%s requested=%s", code, requested)

        if requested:
            return  # stop() owns the transition to STOPPED and the record

        # Unexpected exit → crash. The recovery outcome is derived from the run
        # state that follows, so a single record here is enough.
        self._last_crash = CrashInfo(exit_code=code, at=datetime.now(UTC).isoformat())
        # The server dropped every online player without reporting it; a consumer
        # closes those records at the detection time (design.md D1 tier 2).
        self._notify_unexpected_exit()
        with contextlib.suppress(TransitionError):
            self._sm.transition(RunState.CRASHED)
        self.console.add_marker(f"— bedrock_server exited unexpectedly (code {code}) —")

        if self._maintenance is not None:
            # A maintenance operation owns lifecycle decisions: do not
            # auto-restart. Hand the exit to it to act on (server-lifecycle spec).
            log.warning(
                "server exited during %s maintenance; routing exit to the operation",
                self._maintenance,
            )
            if self._maintenance_exit is not None and not self._maintenance_exit.done():
                self._maintenance_exit.set_result(self._last_exit)
            return

        await self._handle_crash()

    async def _handle_crash(self) -> None:
        now = self._clock()
        window = self._settings.crash_restart_window
        self._crash_times = [t for t in self._crash_times if now - t <= window]
        self._crash_times.append(now)
        threshold = self._settings.crash_restart_threshold

        if threshold <= 0 or not self._auto_restart_enabled:
            log.warning("automatic restart disabled; leaving state=crashed")
            return
        if len(self._crash_times) > threshold:
            log.error(
                "crash %d within %gs exceeds threshold %d; abandoning recovery",
                len(self._crash_times),
                window,
                threshold,
            )
            with contextlib.suppress(TransitionError):
                self._sm.transition(RunState.RECOVERY_ABANDONED)
            self.console.add_marker("— automatic recovery abandoned after repeated crashes —")
            return

        log.warning("attempting automatic restart (%d/%d)", len(self._crash_times), threshold)
        self.console.add_marker("— attempting automatic restart —")
        try:
            async with self._op_lock:
                if self._sm.state != RunState.CRASHED:
                    return
                self._sm.transition(RunState.STARTING)
                await self._spawn_and_await_ready()
        except SupervisorError as exc:
            log.error("automatic restart failed: %s", exc)

    # -- lifecycle: stop ------------------------------------------
    async def stop(self, *, reason: str = "stop") -> None:
        self._reject_if_maintenance()
        async with self._op_lock:
            self._reject_if_maintenance()
            await self._stop_locked(reason=reason)

    async def _stop_locked(self, *, reason: str) -> None:
        state = self._sm.state
        if state in (
            RunState.STOPPED,
            RunState.CRASHED,
            RunState.FAILED,
            RunState.RECOVERY_ABANDONED,
        ):
            # Nothing running. Idempotent for restart-from-stopped.
            if state != RunState.STOPPED:
                with contextlib.suppress(TransitionError):
                    self._sm.transition(RunState.STOPPED)
            self._persist_desired(running=False)
            return
        if state == RunState.STOPPING:
            raise TransitionInProgressError("a stop is already in progress")

        self._stop_requested = True
        self._auto_restart_enabled = False
        # Before the process goes away: BDS reports no per-player disconnects on
        # shutdown, so a consumer must close those records itself (design.md D1).
        self._notify_pre_stop()
        self._sm.transition(RunState.STOPPING)
        assert self._proc is not None

        clean = True
        try:
            await self._proc.write_line("stop")
        except Exception:
            log.warning("could not write 'stop' to stdin; will wait then escalate")

        try:
            await asyncio.wait_for(self._proc.wait(), timeout=self._settings.shutdown_timeout)
        except TimeoutError:
            log.warning(
                "server did not exit within %gs; sending SIGKILL",
                self._settings.shutdown_timeout,
            )
            self._proc.kill()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._proc.wait(), timeout=10.0)
            clean = False

        await self._drain_supervise()
        self._sm.transition(RunState.STOPPED)
        self._record_shutdown(clean=clean, reason="sigkill" if not clean else reason)
        self._persist_desired(running=False)

    async def _force_terminate(self, *, reason: str) -> None:
        """Kill the process without the graceful ``stop`` path (used on readiness
        timeout). Always recorded as unclean."""
        self._stop_requested = True
        self._notify_pre_stop()
        if self._proc is not None:
            self._proc.kill()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._proc.wait(), timeout=10.0)
        await self._drain_supervise()
        self._record_shutdown(clean=False, reason=reason)
        self._persist_desired(running=False)

    async def _drain_supervise(self) -> None:
        for task in (self._pump_task, self._supervise_task):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(asyncio.shield(task), timeout=15.0)
        self._pump_task = None
        self._supervise_task = None
        self._proc = None

    # -- lifecycle: restart --------------------------------------
    async def restart(self) -> None:
        self._reject_if_maintenance()
        async with self._op_lock:
            self._reject_if_maintenance()
            if self._sm.state in (RunState.STARTING, RunState.RUNNING, RunState.STOPPING):
                await self._stop_locked(reason="restart")
            elif self._sm.state != RunState.STOPPED:
                with contextlib.suppress(TransitionError):
                    self._sm.transition(RunState.STOPPED)
            if not self._layout.has_installation():
                raise NoInstallationError("no Bedrock installation is present")
            self.console.add_marker("— restarting —")
            self._sm.transition(RunState.STARTING)
            self._auto_restart_enabled = True
            await self._spawn_and_await_ready()

    # -- cobble lifecycle coupling ------------------------------
    async def aclose(self) -> None:
        """Called when cobble itself is terminating. Stops the child cleanly."""
        self._closing = True
        if self._maintenance is not None:
            log.warning(
                "cobble terminating while a %s operation is in progress; stopping the "
                "server cleanly — the operation must record itself as interrupted",
                self._maintenance,
            )
        async with self._op_lock:
            if self._sm.state in (RunState.STARTING, RunState.RUNNING, RunState.STOPPING):
                await self._stop_locked(reason="cobble_terminate")
                # cobble is going down but the server *was* running: remember that
                # so the next cobble start brings it back.
                self._persist_desired(running=True)

    async def restore(self) -> None:
        """Called on cobble start. Re-launches the server if it was running when
        cobble last stopped."""
        if not self._desired_running():
            return
        if not self._layout.has_installation():
            log.warning("was running before, but no installation present; not restoring")
            return
        log.info("restoring previously-running server")
        try:
            await self.start()
        except SupervisorError as exc:
            log.error("restore failed: %s", exc)

    # -- persistence helpers ------------------------------------
    def _record_shutdown(self, *, clean: bool, reason: str) -> None:
        rec = ShutdownRecord.now(clean=clean, reason=reason)
        self._last_shutdown = rec
        store_last_shutdown(self._settings.shutdown_record_file, rec)

    def _persist_desired(self, *, running: bool) -> None:
        import json

        path = self._settings.runtime_state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"desired_running": running}))
        tmp.replace(path)

    def _desired_running(self) -> bool:
        import json

        try:
            return bool(
                json.loads(self._settings.runtime_state_file.read_text())["desired_running"]
            )
        except (OSError, ValueError, KeyError):
            return False

    # -- misc --------------------------------------------------
    async def send_command(self, command: str) -> None:
        if self._sm.state != RunState.RUNNING or self._proc is None:
            raise NotRunningError("the server is not running")
        await self._proc.write_line(command)

    async def wait_supervise_idle(self) -> None:
        """Test helper: await any in-flight crash handling."""
        task = self._supervise_task
        if task is not None:
            with contextlib.suppress(Exception):
                await task
