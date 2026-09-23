"""Durable, append-only backup history (backup-history spec; tasks 3.1-3.3).

One JSON file under the state directory holding every successful, verified
capture — independent of whether the archive file itself has since been
pruned by retention. ``still_held`` is computed at read time against a
:class:`cobble.backup.store.BackupStore`, never stored, so a backup pruned
after its record was written correctly reads back as no longer held without a
second write (task 3.3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cobble.logging import get_logger

if TYPE_CHECKING:
    from cobble.backup.store import BackupStore

log = get_logger("backup.records")


@dataclass(frozen=True)
class BackupHistoryEntry:
    at: str  # ISO 8601 UTC capture time
    reason: str  # manual | scheduled | pre-update | pre-migration
    bedrock_version: str | None
    size_bytes: int
    archive: str
    still_held: bool

    def to_dict(self) -> dict:
        return {
            "at": self.at,
            "reason": self.reason,
            "bedrock_version": self.bedrock_version,
            "size_bytes": self.size_bytes,
            "archive": self.archive,
            "still_held": self.still_held,
        }


class BackupHistoryStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: list[dict] = self._load()

    # -- persistence ---------------------------------------------
    def _load(self) -> list[dict]:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            log.warning("backup history %s unreadable (%s); starting fresh", self._path, exc)
            return []
        if not isinstance(raw, list):
            log.warning("backup history %s malformed; starting fresh", self._path)
            return []
        records = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                records.append(
                    {
                        "at": str(item["at"]),
                        "reason": str(item["reason"]),
                        "bedrock_version": (
                            None
                            if item.get("bedrock_version") is None
                            else str(item["bedrock_version"])
                        ),
                        "size_bytes": int(item.get("size_bytes", 0)),
                        "archive": str(item["archive"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                log.warning("skipping malformed backup history record: %r", item)
        return records

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._records, indent=2))
        tmp.replace(self._path)

    # -- writes -----------------------------------------------------
    def append(
        self,
        *,
        at: str,
        reason: str,
        bedrock_version: str | None,
        size_bytes: int,
        archive: str,
    ) -> None:
        self._records.append(
            {
                "at": at,
                "reason": reason,
                "bedrock_version": bedrock_version,
                "size_bytes": size_bytes,
                "archive": archive,
            }
        )
        self._save()

    # -- reads --------------------------------------------------------
    def list(self, store: BackupStore) -> list[BackupHistoryEntry]:
        """Every recorded backup, newest first, with ``still_held`` computed
        against ``store`` at read time (task 3.3, 3.4)."""
        held = {e.archive.name for e in store.list(verify=False)}
        entries = [
            BackupHistoryEntry(
                at=r["at"],
                reason=r["reason"],
                bedrock_version=r["bedrock_version"],
                size_bytes=r["size_bytes"],
                archive=r["archive"],
                still_held=r["archive"] in held,
            )
            for r in self._records
        ]
        entries.sort(key=lambda e: e.at, reverse=True)
        return entries
