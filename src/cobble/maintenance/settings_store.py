"""Persisted overlay for the maintenance settings an operator can edit live:
backup retention, whether scheduled backups run at all, and the backup /
update-check schedules (task 1.1).

One JSON file under the state directory, written with the same
read-modify-write-via-tmp-file approach as
:class:`cobble.update.records.UpdateStateStore`. A field absent from the file
means "not overridden" — :class:`cobble.maintenance.service.MaintenanceSettingsService`
is what resolves that against :class:`cobble.settings.Settings`'s fallback
value; this store only knows what has been explicitly set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cobble.logging import get_logger
from cobble.maintenance.schedule_config import ScheduleConfig, ScheduleValidationError

log = get_logger("maintenance.settings_store")


@dataclass
class _State:
    backup_retention: int | None = None
    backup_enabled: bool | None = None
    backup_schedule: ScheduleConfig | None = None
    update_schedule: ScheduleConfig | None = None


class MaintenanceSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._state = self._load()

    # -- persistence ---------------------------------------------
    def _load(self) -> _State:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return _State()
        except (OSError, ValueError) as exc:
            log.warning("maintenance settings %s unreadable (%s); starting fresh", self._path, exc)
            return _State()
        if not isinstance(raw, dict):
            log.warning("maintenance settings %s malformed; starting fresh", self._path)
            return _State()

        state = _State()
        try:
            retention = raw.get("backup_retention")
            if retention is not None:
                state.backup_retention = int(retention)
            enabled = raw.get("backup_enabled")
            if enabled is not None:
                state.backup_enabled = bool(enabled)
            bs = raw.get("backup_schedule")
            if bs is not None:
                state.backup_schedule = ScheduleConfig.from_dict(bs)
            us = raw.get("update_schedule")
            if us is not None:
                state.update_schedule = ScheduleConfig.from_dict(us)
        except (ScheduleValidationError, TypeError, ValueError) as exc:
            log.warning("maintenance settings %s malformed (%s); starting fresh", self._path, exc)
            return _State()
        return state

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "backup_retention": self._state.backup_retention,
            "backup_enabled": self._state.backup_enabled,
            "backup_schedule": (
                None
                if self._state.backup_schedule is None
                else self._state.backup_schedule.to_dict()
            ),
            "update_schedule": (
                None
                if self._state.update_schedule is None
                else self._state.update_schedule.to_dict()
            ),
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._path)

    # -- reads ----------------------------------------------------
    @property
    def backup_retention(self) -> int | None:
        return self._state.backup_retention

    @property
    def backup_enabled(self) -> bool | None:
        return self._state.backup_enabled

    @property
    def backup_schedule(self) -> ScheduleConfig | None:
        return self._state.backup_schedule

    @property
    def update_schedule(self) -> ScheduleConfig | None:
        return self._state.update_schedule

    # -- writes ---------------------------------------------------
    def set(
        self,
        *,
        backup_retention: int | None = None,
        backup_enabled: bool | None = None,
        backup_schedule: ScheduleConfig | None = None,
        update_schedule: ScheduleConfig | None = None,
    ) -> None:
        """Overwrite only the fields passed (non-``None``); leaves the rest of
        the overlay untouched. Persists immediately."""
        if backup_retention is not None:
            self._state.backup_retention = backup_retention
        if backup_enabled is not None:
            self._state.backup_enabled = backup_enabled
        if backup_schedule is not None:
            self._state.backup_schedule = backup_schedule
        if update_schedule is not None:
            self._state.update_schedule = update_schedule
        self._save()
