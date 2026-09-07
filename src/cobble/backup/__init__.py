"""Backup and restore of the Bedrock world and cobble's own state (server-backups).

A backup is a single gzip-compressed tar archive in ``COBBLE_BACKUP_DIR`` named
``cobble-backup-<UTC stamp>.tar.gz``, plus a JSON sidecar
``cobble-backup-<UTC stamp>.tar.gz.json`` written last, atomically. The sidecar is
the completion marker: a capture with no sidecar is interrupted and is never
offered for restore. The archive captures ``data/`` and cobble's ``state_dir/``
whole (no file enumeration), so files added later are included with no code
change.
"""

from __future__ import annotations

from cobble.backup.artifact import (
    BACKUP_ARCHIVE_GLOB,
    BackupError,
    Manifest,
)
from cobble.backup.capture import capture_archive, verify_archive
from cobble.backup.store import BackupEntry, BackupStore

__all__ = [
    "BACKUP_ARCHIVE_GLOB",
    "BackupEntry",
    "BackupError",
    "BackupStore",
    "Manifest",
    "capture_archive",
    "verify_archive",
]
