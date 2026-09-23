"""Layers the maintenance settings overlay over :class:`cobble.settings.Settings`
fallback values (task 1.3), and validates/applies writes (task 5.2).

An untouched install (no overlay file) is unaffected: every effective value
falls back to the corresponding ``Settings`` field, so behavior is identical to
before this change until an operator explicitly saves something in the
Settings tab (design.md "Decisions" #4, migration plan).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cobble.maintenance.schedule_config import ScheduleConfig, ScheduleValidationError, parse_hhmm
from cobble.maintenance.settings_store import MaintenanceSettingsStore
from cobble.settings import Settings

# The mandatory pre-update backup is never a setting (maintenance-settings
# spec: "The pre-update backup is not a configurable setting") — surfaced as a
# fixed marker in the GET response so the UI can render it as an informational
# note with no control.
PRE_UPDATE_BACKUP_ALWAYS_ON = True


@dataclass(frozen=True)
class MaintenanceSettingsView:
    backup_retention: int
    backup_enabled: bool
    backup_schedule: ScheduleConfig
    update_schedule: ScheduleConfig

    def to_dict(self) -> dict:
        return {
            "backup_retention": self.backup_retention,
            "backup_enabled": self.backup_enabled,
            "backup_schedule": self.backup_schedule.to_dict(),
            "update_schedule": self.update_schedule.to_dict(),
            "pre_update_backup_always_on": PRE_UPDATE_BACKUP_ALWAYS_ON,
        }


@dataclass(frozen=True)
class MaintenanceSettingsWriteResult:
    ok: bool
    errors: tuple[str, ...]
    settings: MaintenanceSettingsView | None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "settings": None if self.settings is None else self.settings.to_dict(),
        }


def _legacy_time_is_set(settings: Settings) -> bool:
    return parse_hhmm(settings.maintenance_time) is not None


def _default_schedule_from_settings(settings: Settings, *, enabled: bool) -> ScheduleConfig:
    """The seed a fresh install's schedule reproduces today's behavior with:
    daily, at ``maintenance_time``, enabled iff the corresponding legacy flag
    is *and* ``maintenance_time`` is a parseable time — an empty
    ``maintenance_time`` disabled all scheduled work before this change, and
    still does (task 1.4, design.md Migration Plan)."""
    time = settings.maintenance_time if settings.maintenance_time.strip() else "00:00"
    return ScheduleConfig(
        enabled=enabled and _legacy_time_is_set(settings), time=time, frequency="daily", day=None
    )


class MaintenanceSettingsService:
    def __init__(
        self,
        store: MaintenanceSettingsStore,
        settings: Settings,
        *,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        # Called after a successful write, so the scheduler can recompute its
        # wake time immediately (task 2.4, 5.2).
        self._on_change = on_change

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        self._on_change = callback

    # -- effective reads -------------------------------------------
    def effective_backup_retention(self) -> int:
        overlay = self._store.backup_retention
        return overlay if overlay is not None else self._settings.backup_retention

    def effective_backup_enabled(self) -> bool:
        overlay = self._store.backup_enabled
        if overlay is not None:
            return overlay
        return self._settings.backup_enabled and _legacy_time_is_set(self._settings)

    def effective_backup_schedule(self) -> ScheduleConfig:
        """The backup schedule's time/frequency/day. ``backup_enabled`` (a
        separate top-level setting, matching the legacy ``Settings.backup_enabled``
        name — see task 1.1) is always the single source of truth for whether
        the schedule is enabled, so it is mirrored into the returned
        config's ``enabled`` regardless of what a stored ``backup_schedule``
        happens to carry; the two can never disagree."""
        overlay = self._store.backup_schedule
        base = (
            overlay
            if overlay is not None
            else _default_schedule_from_settings(
                self._settings, enabled=self._settings.backup_enabled
            )
        )
        enabled = self.effective_backup_enabled()
        if base.enabled != enabled:
            base = ScheduleConfig(
                enabled=enabled, time=base.time, frequency=base.frequency, day=base.day
            )
        return base

    def effective_update_schedule(self) -> ScheduleConfig:
        overlay = self._store.update_schedule
        if overlay is not None:
            return overlay
        return _default_schedule_from_settings(
            self._settings, enabled=self._settings.update_enabled
        )

    def effective_view(self) -> MaintenanceSettingsView:
        return MaintenanceSettingsView(
            backup_retention=self.effective_backup_retention(),
            backup_enabled=self.effective_backup_enabled(),
            backup_schedule=self.effective_backup_schedule(),
            update_schedule=self.effective_update_schedule(),
        )

    # -- writes ------------------------------------------------------
    def write(self, changes: dict) -> MaintenanceSettingsWriteResult:
        """Validate and persist ``changes`` all-or-nothing; on success,
        triggers ``on_change`` (the scheduler reschedule, task 2.4).

        Recognised keys: ``backup_retention`` (int >= 1), ``backup_enabled``
        (bool), ``backup_schedule`` / ``update_schedule`` (the ``ScheduleConfig``
        shape). Unknown keys are rejected rather than silently ignored, so a
        client typo is surfaced instead of being a silent no-op.
        """
        errors: list[str] = []
        retention: int | None = None
        enabled: bool | None = None
        backup_schedule: ScheduleConfig | None = None
        update_schedule: ScheduleConfig | None = None

        unknown = set(changes) - {
            "backup_retention",
            "backup_enabled",
            "backup_schedule",
            "update_schedule",
        }
        if unknown:
            errors.append(f"unrecognised setting(s): {', '.join(sorted(unknown))}")

        if "backup_retention" in changes:
            raw = changes["backup_retention"]
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
                errors.append("backup_retention must be an integer >= 1")
            else:
                retention = raw

        if "backup_enabled" in changes:
            raw = changes["backup_enabled"]
            if not isinstance(raw, bool):
                errors.append("backup_enabled must be a boolean")
            else:
                enabled = raw

        if "backup_schedule" in changes:
            try:
                backup_schedule = ScheduleConfig.from_dict(changes["backup_schedule"])
            except ScheduleValidationError as exc:
                errors.append(f"backup_schedule: {exc}")

        if "update_schedule" in changes:
            try:
                update_schedule = ScheduleConfig.from_dict(changes["update_schedule"])
            except ScheduleValidationError as exc:
                errors.append(f"update_schedule: {exc}")

        if errors:
            return MaintenanceSettingsWriteResult(ok=False, errors=tuple(errors), settings=None)

        self._store.set(
            backup_retention=retention,
            backup_enabled=enabled,
            backup_schedule=backup_schedule,
            update_schedule=update_schedule,
        )
        if self._on_change is not None:
            self._on_change()
        return MaintenanceSettingsWriteResult(ok=True, errors=(), settings=self.effective_view())
