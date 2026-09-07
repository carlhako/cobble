"""The backup artifact format and its manifest (task 3.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cobble.logging import get_logger

log = get_logger("backup.artifact")

MANIFEST_FORMAT = 1
ARCHIVE_PREFIX = "cobble-backup-"
ARCHIVE_SUFFIX = ".tar.gz"
BACKUP_ARCHIVE_GLOB = f"{ARCHIVE_PREFIX}*{ARCHIVE_SUFFIX}"
SIDECAR_SUFFIX = ARCHIVE_SUFFIX + ".json"
PARTIAL_SUFFIX = ARCHIVE_SUFFIX + ".partial"

# tar member prefixes for the two captured directories.
CONTENT_DATA = "data"
CONTENT_STATE = "cobble-state"
CONTENTS: tuple[str, ...] = (CONTENT_DATA, CONTENT_STATE)


class BackupError(RuntimeError):
    """A backup could not be captured, read, or verified."""


@dataclass(frozen=True)
class Manifest:
    """What a completed backup contains. Serialised into the JSON sidecar and,
    in a lighter form, as ``manifest.json`` inside the archive."""

    captured_at: str  # ISO 8601 UTC
    bedrock_version: str | None
    shutdown_clean: bool | None
    archive: str  # basename of the .tar.gz
    sha256: str  # hex digest of the compressed archive bytes
    size_bytes: int
    contents: tuple[str, ...] = CONTENTS
    format: int = MANIFEST_FORMAT

    def to_mapping(self) -> dict:
        return {
            "format": self.format,
            "captured_at": self.captured_at,
            "bedrock_version": self.bedrock_version,
            "shutdown_clean": self.shutdown_clean,
            "archive": self.archive,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "contents": list(self.contents),
        }

    @classmethod
    def from_mapping(cls, data: object) -> Manifest:
        if not isinstance(data, dict):
            raise BackupError("manifest is not a JSON object")
        try:
            return cls(
                captured_at=str(data["captured_at"]),
                bedrock_version=(
                    None if data.get("bedrock_version") is None else str(data["bedrock_version"])
                ),
                shutdown_clean=(
                    None if data.get("shutdown_clean") is None else bool(data["shutdown_clean"])
                ),
                archive=str(data["archive"]),
                sha256=str(data["sha256"]),
                size_bytes=int(data["size_bytes"]),
                contents=tuple(str(c) for c in data.get("contents", CONTENTS)),
                format=int(data.get("format", MANIFEST_FORMAT)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupError(f"manifest is malformed: {exc}") from exc

    # -- sidecar IO -------------------------------------------------
    @classmethod
    def read(cls, sidecar: Path) -> Manifest:
        """Load a manifest from its sidecar. Raises :class:`BackupError` on a
        missing, unreadable, or malformed file (task 3.1)."""
        try:
            raw = sidecar.read_text()
        except OSError as exc:
            raise BackupError(f"cannot read manifest {sidecar.name}: {exc}") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise BackupError(f"manifest {sidecar.name} is not valid JSON: {exc}") from exc
        return cls.from_mapping(data)

    @classmethod
    def try_read(cls, sidecar: Path) -> Manifest | None:
        try:
            return cls.read(sidecar)
        except BackupError as exc:
            log.warning("%s", exc)
            return None

    def write_atomic(self, sidecar: Path) -> None:
        """Write the sidecar via a temp file + rename. This is the last step of a
        capture and marks the backup complete."""
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        tmp = sidecar.with_suffix(sidecar.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_mapping(), indent=2))
        tmp.replace(sidecar)


def archive_name(stamp: str) -> str:
    return f"{ARCHIVE_PREFIX}{stamp}{ARCHIVE_SUFFIX}"


def sidecar_for(archive: Path) -> Path:
    return archive.with_name(archive.name + ".json")
