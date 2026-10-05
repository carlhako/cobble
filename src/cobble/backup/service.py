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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cobble.acquisition.layout import Layout
from cobble.acquisition.version import is_newer
from cobble.backup.artifact import CONTENT_DATA, CONTENT_STATE, BackupError, Manifest
from cobble.backup.capture import capture_archive, verify_archive
from cobble.backup.pending import PendingRestore, discard_pending, stage_state, write_marker
from cobble.backup.records import BackupHistoryStore
from cobble.backup.store import BackupEntry, BackupStore
from cobble.logging import get_logger
from cobble.maintenance.service import MaintenanceSettingsService
from cobble.maintenance.settings_store import MaintenanceSettingsStore
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
    # A completed restore staged cobble's state for the next start; cobble must
    # restart to run on it (import-backup-archive design.md D5).
    restarting: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "at": self.at,
            "archive": self.archive,
            "replaced_capture": self.replaced_capture,
            "needs_confirmation": self.needs_confirmation,
            "warning": self.warning,
            "error": self.error,
            "restarting": self.restarting,
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


def _extract_safely(archive: Path, staging: Path) -> None:
    """Extract ``archive`` whole into a fresh ``staging`` through the archive
    reader: no member may escape ``staging``, hard links and special files are
    refused, and symlinks are never created — the vendor-payload links are
    recreated by :meth:`Layout.ensure_payload_symlinks` (design.md D4)."""
    from cobble.worldimport.archive import open_archive, validate_members

    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with open_archive(archive) as reader:
        validate_members(reader, "", staging)
        reader.extract("", staging)


def _extract_over_layout(archive: Path, layout: Layout) -> None:
    """Extract a backup archive and swap its ``data/`` and ``cobble-state/``
    contents into the live layout. Used by the update rollback, which restores
    the pre-update capture of this same instance."""
    staging = layout.bedrock_root / ".restore-staging"
    try:
        _extract_safely(archive, staging)
        data_src = staging / CONTENT_DATA
        state_src = staging / CONTENT_STATE
        if data_src.is_dir():
            _replace_dir_contents(data_src, layout.data_dir)
        if state_src.is_dir():
            _replace_dir_contents(state_src, layout.state_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _stage_restore(archive: Path, layout: Layout) -> list[str]:
    """An operator restore: swap ``data/`` into place now (the server is
    stopped, nothing in cobble holds it) and stage ``cobble-state/`` for the
    next cobble start (design.md D5). Returns the staged state entries."""
    staging = layout.bedrock_root / ".restore-staging"
    try:
        _extract_safely(archive, staging)
        data_src = staging / CONTENT_DATA
        if not data_src.is_dir():
            raise BackupError("the backup holds no data directory")
        _replace_dir_contents(data_src, layout.data_dir)
        return stage_state(staging / CONTENT_STATE, layout.state_dir)
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
        on_restored: Callable[[str], None] | None = None,
        maintenance_settings: MaintenanceSettingsService | None = None,
        history: BackupHistoryStore | None = None,
    ) -> None:
        self._settings = settings
        self._layout = layout
        self._sup = supervisor
        self._clock = clock
        # Called after a completed restore with the restored world's level-name,
        # so the next readiness repairs its gamerules rather than adopting the
        # reverted set (server-gamerules spec; design.md D6).
        self._on_restored = on_restored
        # Retention is read through the maintenance-settings overlay rather than
        # ``settings.backup_retention`` directly (task 1.5), so a live-edited
        # value takes effect without a restart. A caller that does not care
        # about the overlay (most existing tests) gets a service backed by an
        # empty store, which is equivalent to reading ``Settings`` directly.
        self._maintenance_settings = maintenance_settings or MaintenanceSettingsService(
            MaintenanceSettingsStore(settings.state_dir / "maintenance_settings.json"), settings
        )
        self._history = history or BackupHistoryStore(settings.state_dir / "backup_history.json")
        self.store = BackupStore(layout.backup_dir)
        self._busy: str | None = None
        # Set once a restore has staged cobble's state: no further backup or
        # restore may run until cobble restarts and applies it.
        self._restart_pending = False
        self._health: str | None = None
        self._last: BackupOutcome | None = None

    def set_on_restored(self, callback: Callable[[str], None] | None) -> None:
        """Register (or replace) the restored-world callback after construction —
        the runtime wires this once the gamerule manager exists."""
        self._on_restored = callback

    def _restored_level_name(self) -> str:
        from cobble.config.properties import PropertiesDocument

        props = self._layout.data_dir / "server.properties"
        name = ""
        if props.is_file():
            name = (PropertiesDocument.load(props).effective().get("level-name") or "").strip()
        return name or "Bedrock level"

    def _note_restored_world(self) -> None:
        if self._on_restored is None:
            return
        try:
            self._on_restored(self._restored_level_name())
        except Exception:
            log.exception("could not record the restored world for gamerules")

    @property
    def restart_pending(self) -> bool:
        return self._restart_pending

    def note_pending_restore(self, pending: PendingRestore) -> None:
        """Called at startup with the result of applying a staged restore: a
        failed swap is surfaced as the destination's health (design.md D8)."""
        if pending.error is None:
            return
        where = (
            f"; the state replaced by it is saved as {pending.replaced_capture}"
            if pending.replaced_capture
            else ""
        )
        self._health = f"restoring {pending.label} did not complete: {pending.error}{where}"

    # -- observation ---------------------------------------------
    def _refuse_if_busy(self) -> None:
        if self._busy is not None:
            raise BackupConflictError(self._busy)
        if self._restart_pending:
            raise BackupConflictError("restore")

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

    def effective_retention(self) -> int:
        """The number of backups to retain, from the maintenance-settings
        overlay (falling back to ``Settings.backup_retention`` when
        unedited) — task 1.5."""
        return self._maintenance_settings.effective_backup_retention()

    def history(self) -> list:
        """Every recorded backup, newest first, ``still_held`` computed
        against the live store (task 3.3)."""
        return self._history.list(self.store)

    # -- capture -----------------------------------------------
    async def capture(self, *, reason: str = "manual") -> BackupOutcome:
        """Cold capture: stop the server if running, archive ``data/`` + cobble
        state, verify, prune, and return the server to its prior run state
        (tasks 3.3-3.6, 3.8).

        A destination that cannot be written is recorded as an unhealthy
        condition and the server is left untouched (task 3.9). Raises
        :class:`BackupConflictError` if a capture or restore is already running.
        """
        self._refuse_if_busy()
        self._busy = "backup"
        try:
            return await self._capture(reason)
        finally:
            self._busy = None

    async def restore_contents_now(self, archive_name: str) -> None:
        """Swap a backup archive's contents into the live layout, without
        touching the server. For the update state machine's rollback (task 6.7),
        which already holds a maintenance scope and has the server stopped.
        Raises :class:`BackupError` if the archive is missing, unverifiable, or
        unsafe to extract, ``OSError`` if extraction fails."""
        entry = self.store.get(archive_name)
        if entry is None or not entry.restorable:
            raise BackupError(
                f"cannot restore {archive_name}: {entry.reason if entry else 'not found'}"
            )
        from cobble.worldimport.archive import ArchiveError

        try:
            await asyncio.to_thread(
                _extract_over_layout, self._layout.backup_dir / archive_name, self._layout
            )
        except ArchiveError as exc:
            raise BackupError(str(exc)) from exc
        self._layout.ensure_payload_symlinks()
        self._note_restored_world()

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

        await asyncio.to_thread(self.store.prune, self.effective_retention())
        self._health = None
        self._last = BackupOutcome(
            ok=True, at=manifest.captured_at, reason=reason, archive=manifest.archive
        )
        self._history.append(
            at=manifest.captured_at,
            reason=reason,
            bedrock_version=manifest.bedrock_version,
            size_bytes=manifest.size_bytes,
            archive=manifest.archive,
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

        Stops the server cleanly, captures the state being replaced, puts the
        backup's ``data/`` in place and stages its cobble state for the next
        cobble start; the caller then restarts cobble (``restarting`` on the
        outcome; import-backup-archive design.md D5). Refuses if the server
        cannot be stopped cleanly, leaving existing state untouched (5.2). If
        the backup predates the installed version, returns
        ``needs_confirmation`` unless ``confirm_old_version`` is set (5.3).
        """
        self._refuse_if_busy()

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

        return await self.restore_file(self._layout.backup_dir / archive_name, label=archive_name)

    async def restore_file(
        self, archive: Path, *, label: str, operation: str = "restoring"
    ) -> RestoreOutcome:
        """Restore from any cobble backup archive on disk — a held backup or one
        uploaded from another instance. Version gating is the caller's; the
        archive is extracted defensively either way (design.md D4, D5)."""
        self._refuse_if_busy()
        self._busy = "restore"
        try:
            return await self._restore_from(archive, label=label, operation=operation)
        finally:
            self._busy = None

    async def _restore_from(self, archive: Path, *, label: str, operation: str) -> RestoreOutcome:
        now = self._clock().isoformat()

        async with self._sup.maintenance_scope(operation) as handle:
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
                    return RestoreOutcome(False, now, label, error=msg)

            handle.set_step("capturing the state being replaced")
            try:
                replaced = await asyncio.to_thread(
                    capture_archive,
                    self._layout,
                    self._layout.backup_dir,
                    bedrock_version=self._sup.installed_version(),
                    shutdown_clean=(
                        self._sup.last_shutdown.clean if self._sup.last_shutdown else None
                    ),
                    now=self._clock(),
                )
                await asyncio.to_thread(
                    verify_archive, self._layout.backup_dir / replaced.archive, replaced
                )
            except (OSError, BackupError) as exc:
                await self._restore_run_state(handle, was_running)
                return RestoreOutcome(
                    False,
                    now,
                    label,
                    error=f"could not capture a safety copy of the current state: {exc}",
                )

            handle.set_step("putting the backup in place")
            from cobble.worldimport.archive import ArchiveError

            try:
                entries = await asyncio.to_thread(_stage_restore, archive, self._layout)
                self._layout.ensure_payload_symlinks()
                level_name = self._restored_level_name()
                write_marker(
                    self._layout.state_dir,
                    entries=entries,
                    label=label,
                    level_name=level_name,
                    replaced_capture=replaced.archive,
                    was_running=was_running,
                )
            except (OSError, BackupError, ArchiveError) as exc:
                # 5.4 the replaced state is still captured in `replaced`; nothing
                # half-staged is left for the next start to apply (D8).
                log.error("restore failed partway: %s", exc)
                discard_pending(self._layout.state_dir)
                self._layout.ensure_payload_symlinks()
                await self._restore_run_state(handle, was_running)
                return RestoreOutcome(
                    False,
                    now,
                    label,
                    replaced_capture=replaced.archive,
                    error=f"restore failed partway through: {exc}; "
                    f"the replaced state is saved as {replaced.archive}",
                )

            # From here cobble's state is staged: nothing may capture or restore
            # again until the restart applies it. The server stays stopped; the
            # next cobble start returns it to `was_running` (design.md D5).
            self._restart_pending = True
            await asyncio.to_thread(self.store.prune, self.effective_retention())
            log.info(
                "restore staged: %s (replaced state saved as %s); cobble restarts to apply it",
                label,
                replaced.archive,
            )
            return RestoreOutcome(
                True, now, label, replaced_capture=replaced.archive, restarting=True
            )

    async def capture_pre_migration(self, version_dir: Path) -> BackupOutcome:
        """Capture a verified backup of a pre-separation (M1) installation whose
        world and config still live in ``version_dir`` (task 4.2).

        The M1 paths are mapped into the ordinary ``data/…`` archive layout, so
        the result is a normal restorable backup. The server must already be
        stopped (migration runs before any start).
        """
        self._refuse_if_busy()
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
            self._history.append(
                at=manifest.captured_at,
                reason="pre-migration",
                bedrock_version=manifest.bedrock_version,
                size_bytes=manifest.size_bytes,
                archive=manifest.archive,
            )
            log.info("pre-migration backup complete: %s", manifest.archive)
            return self._last
        finally:
            self._busy = None

    # -- helpers used by capture.manifest for restore (section 5) --
    def _manifest_for(self, archive_name: str) -> Manifest | None:
        entry = self.store.get(archive_name)
        return entry.manifest if entry else None
