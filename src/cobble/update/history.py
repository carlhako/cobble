"""Durable, append-only version history (version-history spec; task 4.1).

Distinct from :class:`cobble.update.records.UpdateStateStore`, which keeps
only the single most recent result plus the failed-version quarantine. This
store is a permanent log of every successful update, independent of that
single-slot state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cobble.logging import get_logger

log = get_logger("update.history")


@dataclass(frozen=True)
class VersionHistoryEntry:
    at: str  # ISO 8601 UTC
    from_version: str | None
    to_version: str | None
    trigger: str  # manual | scheduled
    # Settings the update moved to the new version's defaults: {key, from, to}.
    settings_changed: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "at": self.at,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "trigger": self.trigger,
            "settings_changed": [dict(c) for c in self.settings_changed],
        }


def _settings_changed(raw: object) -> list[dict]:
    """Well-formed ``{key, from, to}`` entries only; older records have none."""
    if not isinstance(raw, list):
        return []
    return [
        {"key": str(c["key"]), "from": str(c["from"]), "to": str(c["to"])}
        for c in raw
        if isinstance(c, dict) and {"key", "from", "to"} <= c.keys()
    ]


class UpdateHistoryStore:
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
            log.warning("version history %s unreadable (%s); starting fresh", self._path, exc)
            return []
        if not isinstance(raw, list):
            log.warning("version history %s malformed; starting fresh", self._path)
            return []
        records = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                record = {
                    "at": str(item["at"]),
                    "from_version": (
                        None if item.get("from_version") is None else str(item["from_version"])
                    ),
                    "to_version": (
                        None if item.get("to_version") is None else str(item["to_version"])
                    ),
                    "trigger": str(item["trigger"]),
                }
                if changed := _settings_changed(item.get("settings_changed")):
                    record["settings_changed"] = changed
                records.append(record)
            except (KeyError, TypeError, ValueError):
                log.warning("skipping malformed version history record: %r", item)
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
        from_version: str | None,
        to_version: str | None,
        trigger: str,
        settings_changed: list[dict] | None = None,
    ) -> None:
        record: dict = {
            "at": at,
            "from_version": from_version,
            "to_version": to_version,
            "trigger": trigger,
        }
        if settings_changed:
            record["settings_changed"] = settings_changed
        self._records.append(record)
        self._save()

    # -- reads --------------------------------------------------------
    def list(self) -> list[VersionHistoryEntry]:
        entries = [
            VersionHistoryEntry(
                at=r["at"],
                from_version=r["from_version"],
                to_version=r["to_version"],
                trigger=r["trigger"],
                settings_changed=tuple(r.get("settings_changed") or ()),
            )
            for r in self._records
        ]
        entries.sort(key=lambda e: e.at, reverse=True)
        return entries
