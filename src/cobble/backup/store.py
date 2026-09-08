"""Listing and retention of captured backups (tasks 3.7, 3.8)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cobble.backup.artifact import (
    PARTIAL_SUFFIX,
    SIDECAR_SUFFIX,
    BackupError,
    Manifest,
    sidecar_for,
)
from cobble.backup.capture import verify_archive
from cobble.logging import get_logger

log = get_logger("backup.store")


@dataclass(frozen=True)
class BackupEntry:
    archive: Path
    sidecar: Path
    manifest: Manifest | None
    restorable: bool
    reason: str | None  # why it is not restorable, when it is not

    @property
    def captured_at(self) -> str:
        return self.manifest.captured_at if self.manifest else ""

    @property
    def size_bytes(self) -> int:
        if self.manifest:
            return self.manifest.size_bytes
        try:
            return self.archive.stat().st_size
        except OSError:
            return 0

    def to_dict(self) -> dict:
        return {
            "archive": self.archive.name,
            "captured_at": self.captured_at or None,
            "bedrock_version": self.manifest.bedrock_version if self.manifest else None,
            "shutdown_clean": self.manifest.shutdown_clean if self.manifest else None,
            "size_bytes": self.size_bytes,
            "restorable": self.restorable,
            "reason": self.reason,
        }


class BackupStore:
    """The set of backups held under ``backup_dir``. Purely filesystem-backed;
    every read tolerates a missing directory."""

    def __init__(self, backup_dir: Path) -> None:
        self.dir = backup_dir

    def cleanup_partials(self) -> None:
        if not self.dir.is_dir():
            return
        for p in self.dir.glob("*" + PARTIAL_SUFFIX):
            log.info("removing interrupted capture %s", p.name)
            p.unlink(missing_ok=True)

    def list(self, *, verify: bool = True) -> list[BackupEntry]:
        """Every backup, newest first. A missing destination yields ``[]`` with
        no error (task 3.7). Each entry carries whether it is restorable; a
        capture with no sidecar (interrupted) is not represented at all."""
        if not self.dir.is_dir():
            return []
        entries: list[BackupEntry] = []
        for sidecar in self.dir.glob("*" + SIDECAR_SUFFIX):
            archive = sidecar.with_name(sidecar.name.removesuffix(".json"))
            manifest = Manifest.try_read(sidecar)
            if manifest is None:
                entries.append(BackupEntry(archive, sidecar, None, False, "manifest unreadable"))
                continue
            if not archive.is_file():
                entries.append(
                    BackupEntry(archive, sidecar, manifest, False, "archive file missing")
                )
                continue
            reason: str | None = None
            restorable = True
            if verify:
                try:
                    verify_archive(archive, manifest)
                except BackupError as exc:
                    restorable = False
                    reason = str(exc)
                    log.warning("backup %s failed verification: %s", archive.name, exc)
            entries.append(BackupEntry(archive, sidecar, manifest, restorable, reason))
        entries.sort(key=lambda e: e.captured_at, reverse=True)
        return entries

    def latest_restorable(self) -> BackupEntry | None:
        for entry in self.list():
            if entry.restorable:
                return entry
        return None

    def prune(self, keep: int) -> list[str]:
        """Remove backups beyond ``keep``, oldest first, and never the most
        recent usable one (task 3.8). Returns the names removed."""
        keep = max(0, keep)
        entries = self.list(verify=True)  # newest first
        newest_usable = next((e for e in entries if e.restorable), None)

        removed: list[str] = []
        for entry in entries[keep:]:  # everything past the limit == the oldest
            if entry is newest_usable:
                continue
            self._delete(entry)
            removed.append(entry.archive.name)
        if removed:
            log.info("pruned %d backup(s): %s", len(removed), ", ".join(removed))
        return removed

    def _delete(self, entry: BackupEntry) -> None:
        entry.archive.unlink(missing_ok=True)
        entry.sidecar.unlink(missing_ok=True)

    def get(self, archive_name: str) -> BackupEntry | None:
        archive = self.dir / archive_name
        sidecar = sidecar_for(archive)
        if not sidecar.is_file():
            return None
        manifest = Manifest.try_read(sidecar)
        if manifest is None:
            return BackupEntry(archive, sidecar, None, False, "manifest unreadable")
        if not archive.is_file():
            return BackupEntry(archive, sidecar, manifest, False, "archive file missing")
        try:
            verify_archive(archive, manifest)
        except BackupError as exc:
            return BackupEntry(archive, sidecar, manifest, False, str(exc))
        return BackupEntry(archive, sidecar, manifest, True, None)
