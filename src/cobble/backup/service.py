"""Backup orchestration: cold capture, destination health, retention (section 3).

The service owns *when* a capture happens and the run-state dance around it; the
archive work itself is in :mod:`cobble.backup.capture`. Restore (section 5) is
added here too.
"""

from __future__ import annotations

import asyncio
import errno
import os
import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cobble.acquisition.layout import Layout
from cobble.acquisition.version import is_newer
from cobble.backup.artifact import CONTENT_DATA, CONTENT_STATE, BackupError, Manifest
from cobble.backup.capture import capture_archive, verify_archive
from cobble.backup.store import BackupEntry, BackupStore
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

log = get_logger("backup.service")


class BackupConflictError(RuntimeError):
    """A backup or restore was requested while one is already in progress."""

    code = "backup_in_progress"

    def __init__(self, operation: str) -> None:
        super().__init__(f"a {operation} operation is already in progress")
        self.operation = operation


@dataclass(frozen=True)
class RestoreOutcome:
    ok: bool
    at: str
    archive: str  # the backup that was (or would be) restored
    replaced_capture: str | None = None  # backup of the state that was replaced
    needs_confirmation: bool = False
    warning: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "at": self.at,
            "archive": self.archive,
            "replaced_capture": self.replaced_capture,
            "needs_confirmation": self.needs_confirmation,
            "warning": self.warning,
            "error": self.error,
        }


@dataclass(frozen=True)
class BackupOutcome:
    ok: bool
    at: str  # ISO 8601 UTC
    reason: str  # what triggered it: "manual" | "scheduled" | "pre-update"
    archive: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "at": self.at,
            "reason": self.reason,
            "archive": self.archive,
            "error": self.error,
        }


def _describe_os_error(exc: OSError) -> str:
    if exc.errno == errno.ENOSPC:
        return "backup destination is full"
    if exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM):
        return "backup destination is not writable"
    if exc.errno == errno.ENOENT:
        return "backup destination does not exist"
    return f"backup destination unavailable: {exc}"


def probe_destination(dest_dir: Path) -> str | None:
    """Return a human-readable reason the destination cannot be written, or
    ``None`` if a probe write succeeded. Never raises."""
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        probe = dest_dir / ".cobble-write-test"
        with open(probe, "wb") as fh:
            fh.write(b"ok")
            fh.flush()
            os.fsync(fh.fileno())
        probe.unlink()
    except OSError as exc:
        return _describe_os_error(exc)
    return None


def _replace_dir_contents(src: Path, target: Path) -> None:
    """Replace everything under ``target`` with everything under ``src``.

    Not atomic — the caller keeps a verified capture of ``target`` first (task
    5.4), which is the recovery path if this is interrupted. Uses ``shutil.move``
    so it works when ``src`` and ``target`` are on different filesystems (data/
    is under /srv, cobble state under /var)."""
    target.mkdir(parents=True, exist_ok=True)
    for child in list(target.iterdir()):
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in list(src.iterdir()):
        shutil.move(str(child), str(target / child.name))


def _extract_over_layout(archive: Path, layout: Layout) -> None:
    """Extract a backup archive and swap its ``data/`` and ``cobble-state/``
    contents into the live layout."""
    staging = layout.bedrock_root / ".restore-staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            tar.extractall(staging, filter="tar")
        data_src = staging / CONTENT_DATA
        state_src = staging / CONTENT_STATE
        if data_src.is_dir():
            _replace_dir_contents(data_src, layout.data_dir)
        if state_src.is_dir():
            _replace_dir_contents(state_src, layout.state_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


class BackupService:
    def __init__(
        self,
        settings: Settings,
        layout: Layout,
        supervisor: Supervisor,
        *,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._layout = layout
        self._sup = supervisor
        self._clock = clock
        self.store = BackupStore(layout.backup_dir)
        self._busy: str | None = None
        self._health: str | None = None
        self._last: BackupOutcome | None = None

    # -- observation ---------------------------------------------
    @property
    def health(self) -> str | None:
        """An unhealthy-destination reason, or ``None`` when backups are healthy."""
        return self._health

    @property
    def last_outcome(self) -> BackupOutcome | None:
        return self._last

    @property
    def in_progress(self) -> str | None:
        return self._busy

    def list_backups(self) -> list[BackupEntry]:
        return self.store.list()

    # -- capture -----------------------------------------------
    async def capture(self, *, reason: str = "manual") -> BackupOutcome:
        """Cold capture: stop the server if running, archive ``data/`` + cobble
        state, verify, prune, and return the server to its prior run state
        (tasks 3.3-3.6, 3.8).

        A destination that cannot be written is recorded as an unhealthy
        condition and the server is left untouched (task 3.9). Raises
        :class:`BackupConflictError` if a capture or restore is already running.
        """
        if self._busy is not None:
            raise BackupConflictError(self._busy)
        self._busy = "backup"
        try:
            return await self._capture(reason)
        finally:
            self._busy = None

    async def restore_contents_now(self, archive_name: str) -> None:
        """Swap a backup archive's contents into the live layout, without
        touching the server. For the update state machine's rollback (task 6.7),
        which already holds a maintenance scope and has the server stopped.
        Raises :class:`BackupError` if the archive is missing or unverifiable,
        ``OSError``/``tarfile.TarError`` if extraction fails."""
        entry = self.store.get(archive_name)
        if entry is None or not entry.restorable:
            raise BackupError(
                f"cannot restore {archive_name}: {entry.reason if entry else 'not found'}"
            )
        await asyncio.to_thread(
            _extract_over_layout, self._layout.backup_dir / archive_name, self._layout
        )
        self._layout.ensure_payload_symlinks()

    async def snapshot_now(self, reason: str) -> BackupOutcome:
        """Capture immediately, without touching the server's run state.

        For callers that already hold a maintenance scope and have stopped the
        server themselves — the update state machine's pre-update backup
        (task 6.4). Not guarded by ``_busy``; the caller's maintenance scope
        already excludes a concurrent capture.
        """
        return await self._archive_verify_prune(reason)

    async def _capture(self, reason: str) -> BackupOutcome:
        self.store.cleanup_partials()

        # Pre-flight: if the destination is unavailable, do not stop the server.
        probe = await asyncio.to_thread(probe_destination, self._layout.backup_dir)
        if probe is not None:
            return self._record_failure(reason, probe)

        async with self._sup.maintenance_scope("backing_up") as handle:
            was_running = self._sup.state is RunState.RUNNING
            if was_running:
                handle.set_step("stopping server")
                await self._sup.maintenance_stop(reason="backup")
            handle.set_step("capturing")
            outcome = await self._archive_verify_prune(reason)
            await self._restore_run_state(handle, was_running)
            return outcome

    async def _archive_verify_prune(self, reason: str) -> BackupOutcome:
        """Archive ``data/`` + cobble state, verify, prune. No server
        interaction — the server must already be stopped."""
        self.store.cleanup_partials()
        probe = await asyncio.to_thread(probe_destination, self._layout.backup_dir)
        if probe is not None:
            return self._record_failure(reason, probe)

        rec = self._sup.last_shutdown
        try:
            manifest = await asyncio.to_thread(
                capture_archive,
                self._layout,
                self._layout.backup_dir,
                bedrock_version=self._sup.installed_version(),
                shutdown_clean=rec.clean if rec is not None else None,
                now=self._clock(),
            )
        except OSError as exc:
            return self._record_failure(reason, _describe_os_error(exc))
        except BackupError as exc:
            return self._record_failure(reason, str(exc))

        try:
            await asyncio.to_thread(
                verify_archive, self._layout.backup_dir / manifest.archive, manifest
            )
        except BackupError as exc:
            (self._layout.backup_dir / manifest.archive).unlink(missing_ok=True)
            (self._layout.backup_dir / (manifest.archive + ".json")).unlink(missing_ok=True)
            return self._record_failure(reason, f"capture failed verification: {exc}")

        await asyncio.to_thread(self.store.prune, self._settings.backup_retention)
        self._health = None
        self._last = BackupOutcome(
            ok=True, at=manifest.captured_at, reason=reason, archive=manifest.archive
        )
        log.info("backup complete: %s (%s)", manifest.archive, reason)
        return self._last

    async def _restore_run_state(self, handle, was_running: bool) -> None:
        if was_running and not self._sup.is_closing:
            handle.set_step("starting server")
            await self._sup.maintenance_start()

    def _record_failure(self, reason: str, message: str) -> BackupOutcome:
        self._health = message
        self._last = BackupOutcome(
            ok=False,
            at=self._clock().isoformat(),
            reason=reason,
            error=message,
        )
        log.error("backup failed (%s): %s", reason, message)
        return self._last

    # -- restore (section 5) ------------------------------------
    async def restore(
        self, archive_name: str, *, confirm_old_version: bool = False
    ) -> RestoreOutcome:
        """Restore a captured backup over the live installation (tasks 5.1-5.4).

        Stops the server cleanly, captures the state being replaced, swaps the
        backup contents into place, and starts again. Refuses if the server
        cannot be stopped cleanly, leaving existing state untouched (5.2). If
        the backup predates the installed version, returns
        ``needs_confirmation`` unless ``confirm_old_version`` is set (5.3).
        """
        if self._busy is not None:
            raise BackupConflictError(self._busy)

        entry = self.store.get(archive_name)
        now = self._clock().isoformat()
        if entry is None or entry.manifest is None:
            return RestoreOutcome(False, now, archive_name, error="backup not found")
        if not entry.restorable:
            return RestoreOutcome(
                False, now, archive_name, error=f"backup is not restorable: {entry.reason}"
            )

        installed = self._sup.installed_version()
        recorded = entry.manifest.bedrock_version
        if not confirm_old_version and installed and recorded and is_newer(installed, recorded):
            return RestoreOutcome(
                False,
                now,
                archive_name,
                needs_confirmation=True,
                warning=(
                    f"this backup's world was captured under Bedrock {recorded}, older than "
                    f"the installed {installed}; restoring it rolls the world back"
                ),
            )

        self._busy = "restore"
        try:
            return await self._restore(entry)
        finally:
            self._busy = None

    async def _restore(self, entry: BackupEntry) -> RestoreOutcome:
        assert entry.manifest is not None
        archive_name = entry.manifest.archive
        now = self._clock().isoformat()

        async with self._sup.maintenance_scope("restoring") as handle:
            was_running = self._sup.state is RunState.RUNNING
            if was_running:
                handle.set_step("stopping server")
                await self._sup.maintenance_stop(reason="restore")
                rec = self._sup.last_shutdown
                if rec is not None and not rec.clean:
                    # 5.2 could not stop cleanly: touch nothing, bring the old
                    # server back, report.
                    handle.set_step("restarting after unclean stop")
                    if not self._sup.is_closing:
                        await self._sup.maintenance_start()
                    msg = "server could not be stopped cleanly; nothing was replaced"
                    log.error("restore refused: %s", msg)
                    return RestoreOutcome(False, now, archive_name, error=msg)

            handle.set_step("capturing the state being replaced")
            replaced = await asyncio.to_thread(
                capture_archive,
                self._layout,
                self._layout.backup_dir,
                bedrock_version=self._sup.installed_version(),
                shutdown_clean=(self._sup.last_shutdown.clean if self._sup.last_shutdown else None),
                now=self._clock(),
            )
            try:
                await asyncio.to_thread(
                    verify_archive, self._layout.backup_dir / replaced.archive, replaced
                )
            except BackupError as exc:
                await self._restore_run_state(handle, was_running)
                return RestoreOutcome(
                    False,
                    now,
                    archive_name,
                    error=f"could not capture a safety copy of the current state: {exc}",
                )

            handle.set_step("putting the backup in place")
            try:
                await asyncio.to_thread(
                    _extract_over_layout, self._layout.backup_dir / archive_name, self._layout
                )
            except (OSError, tarfile.TarError) as exc:
                # 5.4 the replaced state is still captured in `replaced`.
                log.error("restore failed partway: %s", exc)
                await self._restore_run_state(handle, was_running)
                return RestoreOutcome(
                    False,
                    now,
                    archive_name,
                    replaced_capture=replaced.archive,
                    error=f"restore failed partway through: {exc}; "
                    f"the replaced state is saved as {replaced.archive}",
                )

            self._layout.ensure_payload_symlinks()
            await asyncio.to_thread(self.store.prune, self._settings.backup_retention)
            await self._restore_run_state(handle, was_running)
            log.info(
                "restore complete: %s (replaced state saved as %s)",
                archive_name,
                replaced.archive,
            )
            return RestoreOutcome(True, now, archive_name, replaced_capture=replaced.archive)

    async def capture_pre_migration(self, version_dir: Path) -> BackupOutcome:
        """Capture a verified backup of a pre-separation (M1) installation whose
        world and config still live in ``version_dir`` (task 4.2).

        The M1 paths are mapped into the ordinary ``data/…`` archive layout, so
        the result is a normal restorable backup. The server must already be
        stopped (migration runs before any start).
        """
        if self._busy is not None:
            raise BackupConflictError(self._busy)
        self._busy = "backup"
        try:
            probe = await asyncio.to_thread(probe_destination, self._layout.backup_dir)
            if probe is not None:
                return self._record_failure("pre-migration", probe)

            sources: dict[str, Path] = {"cobble-state": self._layout.state_dir}
            world = version_dir / "worlds"
            if world.is_dir():
                sources["data/worlds"] = world
            for name in ("server.properties", "allowlist.json", "permissions.json"):
                src = version_dir / name
                if src.is_file():
                    sources[f"data/{name}"] = src

            rec = self._sup.last_shutdown
            try:
                manifest = await asyncio.to_thread(
                    capture_archive,
                    self._layout,
                    self._layout.backup_dir,
                    sources=sources,
                    bedrock_version=self._sup.installed_version(),
                    shutdown_clean=rec.clean if rec is not None else None,
                    now=self._clock(),
                )
                await asyncio.to_thread(
                    verify_archive, self._layout.backup_dir / manifest.archive, manifest
                )
            except (OSError, BackupError) as exc:
                return self._record_failure("pre-migration", str(exc))

            self._health = None
            self._last = BackupOutcome(
                ok=True, at=manifest.captured_at, reason="pre-migration", archive=manifest.archive
            )
            log.info("pre-migration backup complete: %s", manifest.archive)
            return self._last
        finally:
            self._busy = None

    # -- helpers used by capture.manifest for restore (section 5) --
    def _manifest_for(self, archive_name: str) -> Manifest | None:
        entry = self.store.get(archive_name)
        return entry.manifest if entry else None
