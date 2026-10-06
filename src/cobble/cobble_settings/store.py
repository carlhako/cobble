"""Persisted cobble settings: one JSON file under the state directory.

Written with the same tmp-file-and-rename approach as
:class:`cobble.maintenance.settings_store.MaintenanceSettingsStore`. A missing,
unreadable or malformed file reads as "nothing set". The file is instance-local
(``cobble.backup.artifact.INSTANCE_LOCAL``), so a restore never replaces it.
"""

from __future__ import annotations

import json
from pathlib import Path

from cobble.logging import get_logger

log = get_logger("cobble_settings.store")


class CobbleSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._timezone = self._load()

    def _load(self) -> str | None:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("cobble settings %s unreadable (%s); treating as unset", self._path, exc)
            return None
        if not isinstance(raw, dict):
            log.warning("cobble settings %s malformed; treating as unset", self._path)
            return None
        tz = raw.get("timezone")
        if tz is None:
            return None
        if not isinstance(tz, str) or not tz.strip():
            log.warning(
                "cobble settings %s has a malformed timezone; treating as unset", self._path
            )
            return None
        return tz

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"timezone": self._timezone}, indent=2))
        tmp.replace(self._path)

    @property
    def timezone(self) -> str | None:
        return self._timezone

    def set_timezone(self, name: str | None) -> None:
        self._timezone = name
        self._save()
