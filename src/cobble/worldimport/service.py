"""The world-import service: free-space preflight, version gate, and the
stop / capture / replace / start sequence that puts an imported world in place
(sections 3 and 4).

The destructive sequence mirrors :meth:`cobble.backup.service.BackupService._restore`
exactly — a ``maintenance_scope``, a clean stop, a *verified* safety capture
before anything is removed, the swap, the vendor-payload symlinks, and a return
to the prior run state on every exit path. The only differences are the source
(an operator zip, not a cobble tarball) and the target (one world directory, not
all of ``data/``).
"""

from __future__ import annotations

import asyncio
import shutil
import zipfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cobble.acquisition.layout import Layout
from cobble.acquisition.version import is_newer
from cobble.backup.artifact import BackupError
from cobble.backup.capture import capture_archive, verify_archive
from cobble.backup.service import BackupService, _replace_dir_contents
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor
from cobble.worldimport.archive import (
    ArchiveError,
    inspect,
    open_archive,
    validate_members,
)
from cobble.worldimport.staging import StagingSlot

log = get_logger("worldimport.service")

_DEFAULT_LEVEL_NAME = "Bedrock level"
# Slack added to every free-space budget: a capture's compression ratio is
# unpredictable and disk figures are approximations (design.md D9).
_SPACE_MARGIN = 256 * 1024 * 1024


class InsufficientSpaceError(RuntimeError):
    """A free-space preflight refused the operation (design.md D9)."""

    code = "insufficient_space"

    def __init__(self, required: int, available: int, *, what: str) -> None:
        self.required = required
        self.available = available
        super().__init__(
            f"insufficient space to {what}: needs {_fmt_bytes(required)}, "
            f"{_fmt_bytes(available)} available"
        )


def _fmt_bytes(n: int) -> str:
    v = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if v < 1024 or unit == "TiB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return f"{n} B"


def _dir_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_symlink() or not p.is_file():
                continue
            total += p.stat().st_size
        except OSError:
            continue
    return total


@dataclass(frozen=True)
class ImportOutcome:
    """Shaped like :class:`cobble.backup.service.RestoreOutcome` so the frontend's
    existing two-step confirmation pattern carries over (design.md D6)."""

    ok: bool
    at: str
    world: str  # the level-name the world was (or would be) installed under
    replaced_capture: str | None = None
    needs_confirmation: bool = False
    warning: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "at": self.at,
            "world": self.world,
            "replaced_capture": self.replaced_capture,
            "needs_confirmation": self.needs_confirmation,
            "warning": self.warning,
            "error": self.error,
        }


class ImportService:
    def __init__(
        self,
        settings: Settings,
        layout: Layout,
        supervisor: Supervisor,
        backup: BackupService,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        on_restored: Callable[[str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._layout = layout
        self._sup = supervisor
        self._backup = backup
        self._clock = clock
        self._on_restored = on_restored
        self.slot = StagingSlot(settings.state_dir / "import-staging")
        # Nothing survives from a previous run (design.md D8, task 2.4).
        self.slot.sweep()

    def set_on_restored(self, callback: Callable[[str], None] | None) -> None:
        self._on_restored = callback

    # -- inspection (cached beside the archive) --------------------
    def inspect_held(self) -> dict | None:
        """A payload describing the held archive, or ``None`` when none is held.

        ``{"ok": True, "inspection": {...}}`` or ``{"ok": False, "error": "..."}``.
        The result is cached beside the archive so a second read does not rescan
        a multi-gigabyte zip (task 2.5).
        """
        archive = self.slot.held()
        if archive is None:
            return None
        cached = self.slot.load_inspection()
        if cached is not None:
            return cached
        try:
            with open_archive(archive) as zf:
                payload = {"ok": True, "inspection": inspect(zf).to_dict()}
        except ArchiveError as exc:
            payload = {"ok": False, "error": str(exc)}
        self.slot.store_inspection(payload)
        return payload

    async def describe_async(self) -> dict:
        """:meth:`describe` off the event loop — inspecting a held archive runs
        ``testzip`` over a possibly multi-gigabyte file."""
        return await asyncio.to_thread(self.describe)

    def describe(self) -> dict:
        """State for ``GET /api/import`` — the held archive's inspection or an
        empty state, the refusal reason when it cannot be applied, the version
        relation, and any maintenance operation in progress."""
        current_world = self._level_name()
        payload = self.inspect_held()
        if payload is None:
            return {
                "held": False,
                "inspection": None,
                "refusal": None,
                "version": None,
                "current_world": current_world,
            }
        if not payload.get("ok"):
            return {
                "held": True,
                "inspection": None,
                "refusal": payload.get("error"),
                "version": None,
                "current_world": current_world,
            }
        insp = payload["inspection"]
        return {
            "held": True,
            "inspection": insp,
            "refusal": None,
            "version": self._version_relation(insp.get("last_opened_version")),
            "current_world": current_world,
        }

    # -- free space (section 3) ---------------------------------
    def _free_bytes(self) -> int:
        target = self._layout.data_dir
        probe = target if target.exists() else target.parent
        try:
            return shutil.disk_usage(probe).free
        except OSError:
            return 0

    def check_upload_space(self, declared_size: int) -> None:
        """Refuse before the body is read when free space cannot hold the
        declared archive (task 3.1)."""
        required = max(0, declared_size) + _SPACE_MARGIN
        available = self._free_bytes()
        if available < required:
            raise InsufficientSpaceError(required, available, what="hold the upload")

    def _check_apply_space(self, world_uncompressed: int, level_name: str) -> None:
        """The extracted world plus a capture of the world being replaced exist
        at once; refuse before the server is stopped (task 3.2, design.md D9)."""
        current = _dir_size(self._layout.data_dir / "worlds" / level_name)
        current += _dir_size(self._settings.state_dir)
        required = max(0, world_uncompressed) + current + _SPACE_MARGIN
        available = self._free_bytes()
        if available < required:
            raise InsufficientSpaceError(required, available, what="apply the import")

    # -- upload ---------------------------------------------------
    async def receive_upload(
        self, chunks: AsyncIterator[bytes], *, declared_size: int | None
    ) -> dict:
        """Stream an upload to the staging slot and return the inspection of what
        was received. Memory stays flat at the chunk size (design.md D3)."""
        if declared_size is not None:
            self.check_upload_space(declared_size)
        fh = self.slot.open_partial()
        try:
            async for chunk in chunks:
                if chunk:
                    await asyncio.to_thread(fh.write, chunk)
        except BaseException:
            fh.close()
            self.slot.abort_partial()
            raise
        fh.close()
        self.slot.commit_partial()
        return await asyncio.to_thread(self.describe)

    def discard(self) -> None:
        self.slot.clear()

    # -- version gate (design.md D6, task 4.1) -----------------
    def _version_relation(self, world_version: str | None) -> dict:
        installed = self._sup.installed_version()
        if not installed or not world_version:
            relation = "unknown"
        elif is_newer(world_version, installed):
            relation = "newer"
        elif is_newer(installed, world_version):
            relation = "older"
        else:
            relation = "same"
        return {
            "installed": installed,
            "world": world_version,
            "relation": relation,
            "importable": relation != "newer",
        }

    def _version_gate(
        self, world_version: str | None, confirm_old_version: bool, now: str, level_name: str
    ) -> ImportOutcome | None:
        installed = self._sup.installed_version()
        if not installed or not world_version:
            return None  # unknown → proceed
        # A newer world is refused unconditionally — confirmation cannot override.
        if is_newer(world_version, installed):
            return ImportOutcome(
                ok=False,
                at=now,
                world=level_name,
                error=(
                    f"the world was last opened with Bedrock {world_version}, newer than the "
                    f"installed {installed}; a newer world cannot be imported — update the "
                    f"server first"
                ),
            )
        if is_newer(installed, world_version) and not confirm_old_version:
            return ImportOutcome(
                ok=False,
                at=now,
                world=level_name,
                needs_confirmation=True,
                warning=(
                    f"the world was last opened with Bedrock {world_version}, older than the "
                    f"installed {installed}; importing it lets the installed server upgrade "
                    f"the world in place, which cannot be undone"
                ),
            )
        return None

    # -- apply ----------------------------------------------------
    def _level_name(self) -> str:
        from cobble.config.properties import PropertiesDocument

        props = self._layout.data_dir / "server.properties"
        if props.is_file():
            try:
                name = (PropertiesDocument.load(props).effective().get("level-name") or "").strip()
                if name:
                    return name
            except OSError:
                pass
        return _DEFAULT_LEVEL_NAME

    async def apply(self, *, confirm_old_version: bool = False) -> ImportOutcome:
        now = self._clock().isoformat()
        archive = self.slot.held()
        if archive is None:
            return ImportOutcome(False, now, "", error="no archive is held to apply")

        payload = await asyncio.to_thread(self.inspect_held)
        assert payload is not None
        if not payload.get("ok"):
            return ImportOutcome(
                False, now, "", error=payload.get("error") or "the held archive cannot be applied"
            )
        insp: dict = payload["inspection"]
        level_name = self._level_name()

        gate = self._version_gate(
            insp.get("last_opened_version"), confirm_old_version, now, level_name
        )
        if gate is not None:
            return gate

        try:
            self._check_apply_space(int(insp.get("uncompressed_size") or 0), level_name)
        except InsufficientSpaceError as exc:
            return ImportOutcome(False, now, level_name, error=str(exc))

        return await self._run_import(archive, insp, level_name)

    async def _run_import(self, archive: Path, insp: dict, level_name: str) -> ImportOutcome:
        now = self._clock().isoformat()
        world_prefix = insp["world_prefix"]
        dest_world = self._layout.data_dir / "worlds" / level_name

        async with self._sup.maintenance_scope("importing") as handle:
            was_running = self._sup.state is RunState.RUNNING
            try:
                if was_running:
                    handle.set_step("stopping the server")
                    await self._sup.maintenance_stop(reason="import")
                    rec = self._sup.last_shutdown
                    if rec is not None and not rec.clean:
                        handle.set_step("restarting after an unclean stop")
                        if not self._sup.is_closing:
                            await self._sup.maintenance_start()
                        msg = "the server could not be stopped cleanly; nothing was replaced"
                        log.error("import refused: %s", msg)
                        return ImportOutcome(False, now, level_name, error=msg)

                handle.set_step("capturing the world being replaced")
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
                    return ImportOutcome(
                        False,
                        now,
                        level_name,
                        error=f"could not capture a safety copy of the current world: {exc}",
                    )

                handle.set_step("putting the world in place")
                try:
                    await asyncio.to_thread(
                        _extract_world,
                        archive,
                        world_prefix,
                        dest_world,
                        self.slot.root / ".extract",
                    )
                except (OSError, zipfile.BadZipFile, ArchiveError) as exc:
                    log.error("import failed partway: %s", exc)
                    await self._restore_run_state(handle, was_running)
                    return ImportOutcome(
                        False,
                        now,
                        level_name,
                        replaced_capture=replaced.archive,
                        error=(
                            f"import failed partway through: {exc}; the replaced world is "
                            f"saved as {replaced.archive}"
                        ),
                    )

                self._layout.ensure_payload_symlinks()
                await asyncio.to_thread(self._backup.store.prune, self._settings.backup_retention)
                self._note_restored_world(level_name)
                await self._restore_run_state(handle, was_running)
                log.info(
                    "import complete: world %r (replaced world saved as %s)",
                    level_name,
                    replaced.archive,
                )
                return ImportOutcome(True, now, level_name, replaced_capture=replaced.archive)
            finally:
                # The held archive is discarded once an apply has run, whether it
                # succeeded or failed (world-import spec; task 2.3).
                self.slot.clear()

    async def _restore_run_state(self, handle, was_running: bool) -> None:
        if was_running and not self._sup.is_closing:
            handle.set_step("starting the server")
            await self._sup.maintenance_start()

    def _note_restored_world(self, level_name: str) -> None:
        """Reassert the server's configured gamerules rather than adopt the
        imported world's (design.md D2, task 4.6)."""
        if self._on_restored is None:
            return
        try:
            self._on_restored(level_name)
        except Exception:
            log.exception("could not record the imported world for gamerules")


def _extract_world(archive: Path, world_prefix: str, dest_world: Path, workdir: Path) -> None:
    """Extract only the located world subtree, rewrite ``levelname.txt`` to the
    destination directory name, and replace the destination's contents
    (task 4.4 / design.md D2)."""
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            validate_members(zf, world_prefix, workdir)
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if world_prefix and not name.startswith(world_prefix):
                    continue
                rel = name[len(world_prefix) :]
                if not rel:
                    continue
                target = workdir / rel
                if name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
        # The world's recorded display name follows the directory it lives in.
        (workdir / "levelname.txt").write_text(dest_world.name)
        _replace_dir_contents(workdir, dest_world)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
