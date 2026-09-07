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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

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
    "NoInstallationError",
    "NotRunningError",
    "ReadinessTimeoutError",
    "Supervisor",
    "SupervisorError",
    "TransitionError",
    "TransitionInProgressError",
]

log = get_logger("supervisor")

LineSink = Callable[[str], None]
StateListener = Callable[[RunState, RunState], None]


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


@dataclass
class ExitInfo:
    code: int | None
    crashed: bool


@dataclass
class CrashInfo:
    exit_code: int | None
    at: str  # ISO 8601 UTC of the unexpected exit


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

        self._ready_at: float | None = None
        self._last_exit: ExitInfo | None = None
        self._last_crash: CrashInfo | None = None
        self._crash_times: list[float] = []

        self.console = ConsoleBuffer(settings.console_buffer_lines)
        self._last_shutdown = load_last_shutdown(settings.shutdown_record_file)

        self._state_waiters: list[tuple[frozenset[RunState], asyncio.Future[RunState]]] = []
        self._sm.subscribe(self._resolve_state_waiters)

    def _resolve_state_waiters(self, _frm: RunState, to: RunState) -> None:
        still: list[tuple[frozenset[RunState], asyncio.Future[RunState]]] = []
        for targets, fut in self._state_waiters:
            if to in targets and not fut.done():
                fut.set_result(to)
            elif not fut.done():
                still.append((targets, fut))
        self._state_waiters = still

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

    def installed_version(self) -> str | None:
        return self._layout.installed_version()

    def subscribe_state(self, listener: StateListener) -> None:
        self._sm.subscribe(listener)

    def set_line_sink(self, sink: LineSink) -> None:
        self._sink = sink

    # -- lifecycle: start ------------------------------------------
    async def start(self) -> None:
        async with self._op_lock:
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
        binary = self._layout.bedrock_server_binary()
        # If prior output is retained, mark this process boundary so a restart is
        # distinguishable within the console history (server-console spec).
        if len(self.console) > 0:
            self.console.add_marker("— bedrock_server (re)starting —")
        self._proc = BedrockProcess(binary, binary.parent)
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
        with contextlib.suppress(TransitionError):
            self._sm.transition(RunState.CRASHED)
        self.console.add_marker(f"— bedrock_server exited unexpectedly (code {code}) —")
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
        async with self._op_lock:
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
        async with self._op_lock:
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
