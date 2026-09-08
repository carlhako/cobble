"""The update state machine (section 6, server-updates spec).

resolve vendor version
  not newer / quarantined  -> record, stop
acquire (download + extract)          <- SERVER STILL RUNNING (task 6.2)
  fails -> abort, server untouched
--- maintenance window (design.md D4) ---
clean stop
  unclean -> abort, restart previous  (task 6.3)
verified pre-update backup
  fails  -> abort, restart previous   (task 6.4)
activate new version
start, await readiness within readiness_timeout   (task 6.5)
grace window: an exit here is a failure            (task 6.6)
  ready + survived grace -> SUCCESS, prune old version dirs (6.13)
  otherwise -> ROLLBACK: previous version + pre-update world, start   (6.7, 6.8)
    rolled back -> quarantine the failed version                      (6.10)
    cannot start previous -> TERMINAL, cease automatic action         (6.9)
"""

from __future__ import annotations

import asyncio
import contextlib
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from cobble.acquisition.installer import InstallError, install_version
from cobble.acquisition.layout import Layout
from cobble.acquisition.version import is_newer
from cobble.acquisition.version_source import ResolvedVersion, try_resolve_current_version
from cobble.backup.artifact import BackupError
from cobble.backup.service import BackupService
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor, SupervisorError
from cobble.update.records import UpdateRecord, UpdateStateStore

log = get_logger("update.service")

Resolver = Callable[[Settings], ResolvedVersion | None]


class UpdateConflictError(RuntimeError):
    """An update was requested while one is already in progress (task 6.14)."""

    code = "update_in_progress"


@dataclass(frozen=True)
class UpdateCheck:
    installed: str | None
    available: str | None
    up_to_date: bool
    skipped: bool
    skipped_reason: str | None
    error: str | None

    def to_dict(self) -> dict:
        return {
            "installed": self.installed,
            "available": self.available,
            "up_to_date": self.up_to_date,
            "skipped": self.skipped,
            "skipped_reason": self.skipped_reason,
            "error": self.error,
        }


@dataclass(frozen=True)
class UpdateResult:
    ok: bool
    status: str  # success | up_to_date | skipped | aborted | rolled_back | terminal
    detail: str
    from_version: str | None = None
    to_version: str | None = None
    step: str | None = None  # the step at which it failed, when it failed
    rolled_back: bool = False
    terminal: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "detail": self.detail,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "step": self.step,
            "rolled_back": self.rolled_back,
            "terminal": self.terminal,
        }


class UpdateService:
    def __init__(
        self,
        settings: Settings,
        layout: Layout,
        supervisor: Supervisor,
        backup: BackupService,
        *,
        resolver: Resolver = try_resolve_current_version,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._layout = layout
        self._sup = supervisor
        self._backup = backup
        self._resolve = resolver
        self._clock = clock
        self._store = UpdateStateStore(settings.state_dir / "updates.json")
        self._busy: str | None = None
        # Terminal state: rollback could not restore service. No further
        # automatic action until an operator intervenes (task 6.9).
        self._terminal = False

    # -- observation -------------------------------------------
    @property
    def in_progress(self) -> str | None:
        return self._busy

    @property
    def terminal(self) -> bool:
        return self._terminal

    @property
    def last_result(self) -> UpdateRecord | None:
        return self._store.last_result

    @property
    def last_check_at(self) -> str | None:
        return self._store.last_check_at

    @property
    def available_version(self) -> str | None:
        return self._store.last_available

    def failed_versions(self) -> dict:
        return {
            v: {"step": fv.step, "at": fv.at, "output_tail": fv.output_tail}
            for v, fv in self._store.failed_versions.items()
        }

    def is_skipping(self, version: str | None) -> bool:
        return bool(version) and self._store.is_failed(version)  # type: ignore[arg-type]

    def diagnostics(self) -> dict | None:
        """The most recent failed-update diagnostics: version attempted, failing
        step, and captured output (task 6.12 / 8.4)."""
        rec = self._store.last_result
        if rec is not None and rec.status in ("rolled_back", "terminal", "aborted"):
            return {
                "version": rec.to_version or rec.from_version,
                "step": rec.step,
                "status": rec.status,
                "detail": rec.detail,
                "output": rec.output_tail,
                "at": rec.at,
            }
        return None

    def clear_failed(self, version: str | None = None) -> list[str]:
        """Clear the quarantine record for a version (or all). Also lifts the
        terminal state so an update may be attempted again (task 6.11)."""
        cleared = self._store.clear_failed(version)
        self._terminal = False
        return cleared

    # -- check (task 6.1) -------------------------------------
    async def check(self) -> UpdateCheck:
        installed = self._sup.installed_version()
        resolved = await asyncio.to_thread(self._resolve, self._settings)
        if resolved is None:
            return UpdateCheck(
                installed=installed,
                available=self._store.last_available,
                up_to_date=False,
                skipped=False,
                skipped_reason=None,
                error="vendor source unreachable or returned an unusable response",
            )
        self._store.set_last_check(available=resolved.version)
        if installed and not is_newer(resolved.version, installed):
            return UpdateCheck(installed, resolved.version, True, False, None, None)
        if self._store.is_failed(resolved.version):
            fv = self._store.get_failed(resolved.version)
            reason = f"version {resolved.version} previously failed an update"
            if fv is not None:
                reason += f" at the '{fv.step}' step"
            return UpdateCheck(installed, resolved.version, False, True, reason, None)
        return UpdateCheck(installed, resolved.version, False, False, None, None)

    # -- apply (tasks 6.2-6.14) --------------------------------
    async def apply(self, *, reason: str = "manual") -> UpdateResult:
        if self._busy is not None:
            raise UpdateConflictError(f"an {self._busy} operation is already in progress")
        if self._terminal:
            return self._record(
                "terminal",
                "a previous rollback failed to restore service; operator intervention "
                "is required before further updates",
            )
        self._busy = "update"
        try:
            return await self._apply(reason)
        finally:
            self._busy = None

    async def _apply(self, reason: str) -> UpdateResult:
        installed = self._sup.installed_version()
        resolved = await asyncio.to_thread(self._resolve, self._settings)
        if resolved is None:
            # 6.1 running server unaffected; nothing acquired.
            return self._record(
                "aborted",
                "vendor source unreachable; no update attempted",
                from_version=installed,
            )
        self._store.set_last_check(available=resolved.version)
        new = resolved.version

        if installed and not is_newer(new, installed):
            return self._record("up_to_date", f"installed {installed} is the current release")
        if self._store.is_failed(new):
            fv = self._store.get_failed(new)
            step = fv.step if fv else "a previous"
            return self._record(
                "skipped",
                f"{new} previously failed at the '{step}' step and is not retried automatically",
                from_version=installed,
                to_version=new,
            )

        # 6.2 acquire with the server still running.
        try:
            await asyncio.to_thread(install_version, resolved, self._layout, self._settings)
        except InstallError as exc:
            return self._record(
                "aborted",
                f"acquisition of {new} failed: {exc}",
                from_version=installed,
                to_version=new,
                step="acquire",
            )
        if self._sup.state is RunState.STOPPING or self._sup.state is RunState.STARTING:
            # extremely unlikely (acquire does not touch the server), but never
            # open a maintenance window over a live transition.
            return self._record(
                "aborted",
                "a lifecycle transition was in progress; update deferred",
                from_version=installed,
                to_version=new,
                step="acquire",
            )

        previous = installed
        async with self._sup.maintenance_scope("updating") as handle:
            was_running = self._sup.state is RunState.RUNNING
            handle.set_step(f"stopping {previous or 'server'}")
            if was_running:
                await self._sup.maintenance_stop(reason="update")

            rec = self._sup.last_shutdown
            if was_running and rec is not None and not rec.clean:
                # 6.3 never build a rollback point on a torn world.
                await self._start(handle, "restarting the previous version")
                return self._record(
                    "aborted",
                    "the pre-update shutdown was unclean; update abandoned",
                    from_version=previous,
                    to_version=new,
                    step="stop",
                )

            handle.set_step("capturing a verified pre-update backup")
            pre = await self._backup.snapshot_now("pre-update")
            if not pre.ok:
                # 6.4
                await self._start(handle, "restarting the previous version")
                return self._record(
                    "aborted",
                    f"pre-update backup could not be captured or verified: {pre.error}",
                    from_version=previous,
                    to_version=new,
                    step="backup",
                )
            pre_archive = pre.archive
            assert pre_archive is not None

            handle.set_step(f"activating {new}")
            self._layout.set_active_version(new)

            handle.set_step(f"starting {new}")
            failure: str | None = None
            failing_step = "readiness"
            try:
                await self._sup.maintenance_start()  # 6.5 awaits readiness
            except SupervisorError as exc:
                failure = f"the new version did not signal readiness: {exc}"
            else:
                # 6.6 post-readiness grace window.
                handle.set_step(f"watching {new} through the grace window")
                try:
                    async with asyncio.timeout(self._settings.update_grace_seconds):
                        exit_info = await handle.wait_exit()
                    failure = (
                        f"the new version exited (code {exit_info.code}) within the "
                        f"{self._settings.update_grace_seconds:g}s grace window"
                    )
                    failing_step = "grace-window"
                except TimeoutError:
                    failure = None  # survived the grace window

            if failure is None:
                # 6.13 keep the replaced version as the rollback source; prune older.
                handle.set_step("pruning superseded versions")
                keep = {new} | ({previous} if previous else set())
                await asyncio.to_thread(self._layout.prune_versions, keep)
                return self._record(
                    "success",
                    f"updated {previous or '(unknown)'} -> {new}",
                    from_version=previous,
                    to_version=new,
                )

            return await self._rollback(handle, previous, new, pre_archive, failure, failing_step)

    # -- rollback (tasks 6.7-6.9) ------------------------------
    async def _rollback(
        self,
        handle,
        previous: str | None,
        failed_version: str,
        pre_archive: str,
        reason: str,
        failing_step: str,
    ) -> UpdateResult:
        output_tail = self._console_tail()
        log.error("update to %s failed (%s); rolling back", failed_version, reason)

        # Make sure the failed process is gone before touching the installation.
        if self._sup.state in (RunState.RUNNING, RunState.STARTING, RunState.STOPPING):
            with contextlib.suppress(SupervisorError):
                await self._sup.maintenance_stop(reason="rollback")

        if not previous:
            self._store.add_failed(failed_version, failing_step, output_tail)
            self._terminal = True
            return self._record(
                "terminal",
                f"update to {failed_version} failed and there is no previous version to "
                f"roll back to ({reason})",
                to_version=failed_version,
                step=failing_step,
                output_tail=output_tail,
            )

        handle.set_step(f"reactivating {previous}")
        self._layout.set_active_version(previous)

        # 6.8 always restore the world from the pre-update backup, even if the
        # failed version never became ready.
        handle.set_step("restoring the world from the pre-update backup")
        try:
            await self._backup.restore_contents_now(pre_archive)
        except (BackupError, OSError, tarfile.TarError) as exc:
            self._store.add_failed(failed_version, failing_step, output_tail)
            self._terminal = True
            return self._record(
                "terminal",
                f"rollback could not restore the pre-update world: {exc}",
                from_version=failed_version,
                to_version=previous,
                step="rollback-restore",
                output_tail=output_tail,
            )

        handle.set_step(f"starting {previous}")
        try:
            await self._sup.maintenance_start()
        except SupervisorError as exc:
            # 6.9 terminal: cease automatic action, change nothing further.
            self._store.add_failed(failed_version, failing_step, output_tail)
            self._terminal = True
            return self._record(
                "terminal",
                f"rollback reactivated {previous} but it would not start ({exc}); "
                f"operator intervention required",
                from_version=failed_version,
                to_version=previous,
                step="rollback-start",
                output_tail=output_tail,
            )

        # 6.10 quarantine so the scheduler does not retry this version nightly.
        self._store.add_failed(failed_version, failing_step, output_tail)
        return self._record(
            "rolled_back",
            f"update to {failed_version} failed ({reason}); rolled back to {previous} "
            f"and restored the pre-update world",
            from_version=failed_version,
            to_version=previous,
            rolled_back=True,
            output_tail=output_tail,
        )

    # -- helpers ----------------------------------------------
    async def _start(self, handle, step: str) -> None:
        handle.set_step(step)
        if not self._sup.is_closing:
            with contextlib.suppress(SupervisorError):
                await self._sup.maintenance_start()

    def _console_tail(self, lines: int = 300) -> str:
        try:
            snap = self._sup.console.snapshot()
        except Exception:
            return ""
        return "\n".join(line.text for line in snap[-lines:])

    def _record(
        self,
        status: str,
        detail: str,
        *,
        from_version: str | None = None,
        to_version: str | None = None,
        rolled_back: bool = False,
        step: str | None = None,
        output_tail: str = "",
    ) -> UpdateResult:
        record = UpdateRecord(
            status=status,
            at=self._clock().isoformat(),
            detail=detail,
            from_version=from_version,
            to_version=to_version,
            step=step,
            output_tail=output_tail,
        )
        self._store.set_last_result(record)
        terminal = status == "terminal"
        log.info("update outcome: %s — %s", status, detail)
        return UpdateResult(
            ok=record.ok,
            status=status,
            detail=detail,
            from_version=from_version,
            to_version=to_version,
            step=step,
            rolled_back=rolled_back,
            terminal=terminal,
        )
