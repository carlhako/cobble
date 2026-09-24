"""Requesting, following, and reporting a cobble upgrade (cobble-self-update spec;
design.md D2-D5).

Cobble runs unprivileged and cannot replace itself. An upgrade is therefore a
*request*: after a verified backup, cobble atomically writes
``<state_dir>/upgrade/request.json`` naming the exact release tag it reported
and a fresh request id.
The root helper's systemd path unit reacts to that file, installs that release,
and restarts cobble. Cobble learns the outcome from the helper's
``<upgrade_status_dir>/status.json``, a root-owned file it can only read. The
helper echoes the request id in every status it writes; a status carrying any
other id (an earlier attempt, even at the same tag) is never this request's.

Durable files in cobble's state directory:

- ``upgrade_pending.json`` — ``{from, to, tag, request_id, requested_at}`` while an upgrade is
  outstanding. It is authoritative for ``from``, and it survives the restart
  the helper causes, so the upgraded cobble can report what happened.
- ``upgrade_last.json`` — the most recent finished upgrade's outcome.

While cobble waits for the helper it holds the ``cobble_upgrade`` maintenance
scope with the server stopped (D5), so no second stop happens when cobble is
restarted. If the helper reports failure, or nothing finishes before
``upgrade_timeout_seconds``, cobble gives up, releases maintenance, and restarts
the server if it was running. Any unexpected error while the server is stopped
does the same.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cobble import __version__
from cobble.access.documents import atomic_write_text
from cobble.backup.service import BackupService
from cobble.logging import get_logger
from cobble.selfupdate.release_check import ReleaseChecker, now_iso
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import MaintenanceConflictError, Supervisor

log = get_logger("selfupdate.upgrade")

OPERATION = "cobble_upgrade"
TERMINAL = ("succeeded", "failed", "rejected")
POLL_SECONDS = 2.0
# After a restart, keep following a helper that still reports ``running`` for at
# least this long, even past ``upgrade_timeout_seconds``: the installer restarts
# cobble *before* the helper writes its final status.
FOLLOW_GRACE_SECONDS = 300.0


class UpgradeError(Exception):
    """An upgrade request that cannot go ahead. ``code`` is the API's 409 code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class HelperStatus:
    request_id: str | None
    tag: str | None
    state: str | None  # running | succeeded | failed | rejected
    finished_at: str | None
    exit_code: int | None
    log_tail: str | None
    error: str | None


def manual_command(settings: Settings) -> str:
    return (
        f"curl -fsSL https://github.com/{settings.release_repo}"
        "/releases/latest/download/install.sh | bash"
    )


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data))


def _at_or_after(when: object, since: object) -> bool:
    """Whether ISO timestamp ``when`` is at or after ``since``; ``False`` if either
    does not parse."""
    try:
        return datetime.fromisoformat(str(when)) >= datetime.fromisoformat(str(since))
    except (TypeError, ValueError):
        return False


class UpgradeService:
    def __init__(
        self,
        settings: Settings,
        supervisor: Supervisor,
        backup: BackupService,
        release_check: ReleaseChecker,
        *,
        current: str = __version__,
        now: Callable[[], str] = now_iso,
        clock: Callable[[], float] | None = None,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._settings = settings
        self._sup = supervisor
        self._backup = backup
        self._release = release_check
        self.current = current
        self._now = now
        self._clock = clock
        self._poll = poll_seconds
        self._task: asyncio.Task[None] | None = None
        self._follow_task: asyncio.Task[None] | None = None

    # -- paths -----------------------------------------------------------
    @property
    def request_file(self) -> Path:
        return self._settings.upgrade_request_dir / "request.json"

    @property
    def processing_file(self) -> Path:
        return self._settings.upgrade_request_dir / "request.processing"

    @property
    def status_file(self) -> Path:
        return self._settings.upgrade_status_dir / "status.json"

    @property
    def pending_file(self) -> Path:
        return self._settings.state_dir / "upgrade_pending.json"

    @property
    def last_file(self) -> Path:
        return self._settings.state_dir / "upgrade_last.json"

    def _time(self) -> float:
        return self._clock() if self._clock is not None else asyncio.get_running_loop().time()

    # -- helper --------------------------------------------------------------
    def helper_installed(self) -> bool:
        return self._settings.upgrade_helper_path.is_file() and (
            self._settings.upgrade_status_dir.is_dir()
        )

    def helper_status(self) -> HelperStatus | None:
        data = _read_json(self.status_file)
        if data is None:
            return None
        exit_code = data.get("exit_code")
        rid = data.get("request_id")
        return HelperStatus(
            request_id=rid if isinstance(rid, str) else None,
            tag=data.get("tag") if isinstance(data.get("tag"), str) else None,
            state=data.get("state") if isinstance(data.get("state"), str) else None,
            finished_at=data.get("finished_at"),
            exit_code=exit_code if isinstance(exit_code, int) else None,
            log_tail=data.get("log_tail") if isinstance(data.get("log_tail"), str) else None,
            error=data.get("error") if isinstance(data.get("error"), str) else None,
        )

    def _helper_status_for(self, request_id: object, requested_at: object) -> HelperStatus | None:
        """The helper's status if it concerns this request, matched by request id.
        A request the helper could not even read an id from is recorded as
        rejected with no id; it counts when it finished after this request was
        made."""
        st = self.helper_status()
        if st is None:
            return None
        if st.request_id is not None:
            return st if st.request_id == request_id else None
        if st.state == "rejected" and _at_or_after(st.finished_at, requested_at):
            return st
        return None

    # -- view ----------------------------------------------------------------
    def in_progress(self) -> bool:
        busy = any(t is not None and not t.done() for t in (self._task, self._follow_task))
        return busy or self.pending_file.exists()

    def view(self) -> dict | None:
        """The in-flight upgrade, else the last finished one, else ``None``."""
        pending = _read_json(self.pending_file)
        if pending is not None:
            st = self._helper_status_for(pending.get("request_id"), pending.get("requested_at"))
            # Any status for this request means the helper has taken it; a
            # terminal one is still "running" until cobble concludes it.
            state = "running" if st is not None else "pending"
            return {
                "state": state,
                "from": pending.get("from"),
                "to": pending.get("to"),
                "requested_at": pending.get("requested_at"),
                "finished_at": None,
                "error": None,
                "log_tail": None,
            }
        return _read_json(self.last_file)

    # -- request -------------------------------------------------------------
    async def request(self, version: str) -> dict:
        """Validate, back up, and hand the upgrade to the helper. Returns once
        the request file is written (the view is then ``pending``). Raises
        :class:`UpgradeError` for a refusal or a failed pre-upgrade backup."""
        if self.in_progress():
            raise UpgradeError("upgrade_in_progress", "an upgrade is already pending or running")
        if not self.helper_installed():
            raise UpgradeError(
                "helper_not_installed",
                "the upgrade helper is not installed; run the installer as root to upgrade",
            )
        state = self._release.state
        if not self._release.update_available() or state.latest is None or state.tag is None:
            raise UpgradeError("no_update_available", "no newer cobble release is known")
        if version.lstrip("v") != state.latest:
            raise UpgradeError(
                "version_mismatch",
                f"requested {version!r} but the available release is {state.latest!r}",
            )
        if self._sup.maintenance is not None:
            raise UpgradeError(
                "maintenance_conflict", f"a {self._sup.maintenance} operation is in progress"
            )

        accepted: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(
            self._run(state.tag, state.latest, accepted), name="cobble-upgrade"
        )
        try:
            await asyncio.shield(accepted)
        except MaintenanceConflictError as exc:
            raise UpgradeError("maintenance_conflict", str(exc)) from exc
        return self.view() or {}

    async def _run(self, tag: str, to: str, accepted: asyncio.Future[None]) -> None:
        def reject(exc: BaseException) -> None:
            if not accepted.done():
                accepted.set_exception(exc)

        try:
            async with self._sup.maintenance_scope(OPERATION) as handle:
                was_running = self._sup.state is RunState.RUNNING
                try:
                    await self._hand_off(handle, tag, to, was_running, accepted, reject)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # The server may be stopped and a request outstanding: never
                    # leave either behind on an unexpected error.
                    log.exception("cobble upgrade failed")
                    if self.pending_file.exists():
                        self._finish_pending(("failed", f"the upgrade failed: {exc}", None))
                    with contextlib.suppress(FileNotFoundError):
                        self.request_file.unlink()
                    await self._resume(handle, was_running)
                    reject(exc)
        except asyncio.CancelledError:
            # cobble is being stopped — normally by the helper's restart. The
            # pending record stays for the next start to reconcile.
            reject(UpgradeError("cancelled", "cobble stopped before the upgrade was requested"))
            raise
        except Exception as exc:
            log.exception("cobble upgrade failed")
            reject(exc)

    async def _hand_off(
        self,
        handle,
        tag: str,
        to: str,
        was_running: bool,
        accepted: asyncio.Future[None],
        reject: Callable[[BaseException], None],
    ) -> None:
        """Stop, back up, write the request, and wait for the helper."""
        if was_running:
            handle.set_step("stopping server")
            await self._sup.maintenance_stop(reason="cobble-upgrade")
        handle.set_step("capturing a verified backup")
        pre = await self._backup.snapshot_now("pre-upgrade")
        if not pre.ok:
            message = f"pre-upgrade backup could not be captured or verified: {pre.error}"
            self._record_last("failed", self.current, to, message)
            await self._resume(handle, was_running)
            reject(UpgradeError("backup_failed", message))
            return

        # The backup's stop cleared the desired state; restore it so the
        # upgraded cobble brings the server back (spec: running intent).
        if was_running:
            self._sup.remember_running_for_restart()
        request_id = uuid.uuid4().hex
        requested_at = self._now()
        _write_json(
            self.pending_file,
            {
                "from": self.current,
                "to": to,
                "tag": tag,
                "request_id": request_id,
                "requested_at": requested_at,
            },
        )
        _write_json(self.request_file, {"tag": tag, "request_id": request_id})
        log.info("cobble upgrade to %s requested; waiting for the helper", tag)
        accepted.set_result(None)

        failure = await self._await_helper(handle, tag, request_id, requested_at)
        # Only reached when this cobble was *not* replaced: the helper
        # failed, rejected the request, or never finished.
        self._finish_pending(failure)
        with contextlib.suppress(FileNotFoundError):
            self.request_file.unlink()
        await self._resume(handle, was_running)

    async def _await_helper(
        self, handle, tag: str, request_id: str, requested_at: str
    ) -> tuple[str, str | None, HelperStatus | None]:
        """Poll the helper's status until it is terminal or the timeout passes.
        Returns ``(state, error, status)`` for a non-success outcome."""
        handle.set_step("waiting for the upgrade helper")
        deadline = self._time() + self._settings.upgrade_timeout_seconds
        installing = False
        while self._time() < deadline:
            st = self._helper_status_for(request_id, requested_at)
            if st is not None and st.state == "running" and not installing:
                installing = True
                handle.set_step(f"installing cobble {tag}")
            if st is not None and st.state in ("failed", "rejected"):
                return st.state, st.error or f"the upgrade helper reported {st.state}", st
            if st is not None and st.state == "succeeded":
                # The installer restarts cobble, so this process normally never
                # sees success. If it does, the new code is not what is running.
                return "failed", "the helper finished but cobble was not restarted", st
            await asyncio.sleep(self._poll)
        return (
            "failed",
            f"the upgrade helper did not finish within {self._settings.upgrade_timeout_seconds:g}s",
            self._helper_status_for(request_id, requested_at),
        )

    async def _resume(self, handle, was_running: bool) -> None:
        if was_running and not self._sup.is_closing:
            handle.set_step("starting server")
            try:
                await self._sup.maintenance_start()
            except Exception:
                log.exception("could not restart the server after the cobble upgrade gave up")

    # -- outcome ---------------------------------------------------------------
    def _record_last(
        self,
        state: str,
        from_version: str | None,
        to: str | None,
        error: str | None,
        *,
        requested_at: str | None = None,
        log_tail: str | None = None,
    ) -> None:
        _write_json(
            self.last_file,
            {
                "state": state,
                "from": from_version,
                "to": to,
                "requested_at": requested_at,
                "finished_at": self._now(),
                "error": error,
                "log_tail": log_tail,
            },
        )

    def _finish_pending(self, outcome: tuple[str, str | None, HelperStatus | None]) -> None:
        state, error, st = outcome
        pending = _read_json(self.pending_file) or {}
        log.warning("cobble upgrade to %s did not complete: %s", pending.get("to"), error)
        self._record_last(
            state,
            pending.get("from"),
            pending.get("to"),
            error,
            requested_at=pending.get("requested_at"),
            log_tail=st.log_tail if st is not None else None,
        )
        self.pending_file.unlink(missing_ok=True)

    # -- startup reconciliation ------------------------------------------------
    def start(self) -> None:
        """On cobble start: if an upgrade was outstanding, follow it to its end.

        The helper's installer restarts cobble *before* it writes the final
        status, so a fresh start routinely sees ``running`` and must keep
        polling rather than call the upgrade interrupted."""
        if self.pending_file.exists() and self._follow_task is None:
            self._follow_task = asyncio.create_task(self._follow(), name="cobble-upgrade-follow")

    async def _follow(self) -> None:
        pending = _read_json(self.pending_file)
        if pending is None:
            self.pending_file.unlink(missing_ok=True)
            return
        request_id = pending.get("request_id")
        requested = pending.get("requested_at")
        try:
            elapsed = (datetime.now(UTC) - datetime.fromisoformat(requested)).total_seconds()
        except (TypeError, ValueError):
            elapsed = 0.0
        remaining = max(0.0, self._settings.upgrade_timeout_seconds - elapsed)
        started = self._time()
        deadline = started + remaining
        grace_deadline = started + FOLLOW_GRACE_SECONDS
        while True:
            st = self._helper_status_for(request_id, requested)
            if st is not None and st.state in TERMINAL:
                self._conclude(pending, st)
                return
            now = self._time()
            # A helper still reporting "running" is normally the installer
            # finishing up after restarting us: give it a grace period.
            helper_busy = st is not None and st.state == "running"
            if now >= deadline and not (helper_busy and now < grace_deadline):
                self._conclude(pending, st, interrupted=True)
                return
            await asyncio.sleep(self._poll)

    def _conclude(
        self, pending: dict, st: HelperStatus | None, *, interrupted: bool = False
    ) -> None:
        to = pending.get("to")
        if interrupted:
            state, error = "failed", "the upgrade was interrupted before it finished"
        elif st is not None and st.state == "succeeded":
            if to == self.current:
                state, error = "succeeded", None
            else:
                state = "failed"
                error = f"the helper reported success but cobble {self.current} is running"
        else:
            state = st.state if st is not None and st.state else "failed"
            error = (st.error if st is not None else None) or f"the upgrade helper reported {state}"
        if state == "succeeded":
            log.info("cobble upgraded %s -> %s", pending.get("from"), to)
        else:
            log.warning("cobble upgrade to %s: %s", to, error)
        self._record_last(
            state,
            pending.get("from"),
            to,
            error,
            requested_at=pending.get("requested_at"),
            log_tail=st.log_tail if st is not None else None,
        )
        self.pending_file.unlink(missing_ok=True)
        with contextlib.suppress(FileNotFoundError):
            self.request_file.unlink()

    async def stop(self) -> None:
        for task in (self._task, self._follow_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
