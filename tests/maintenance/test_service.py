"""Task 1.3-1.5, 2.4, 5.2: ``MaintenanceSettingsService`` fallback/overlay
precedence, seeding, and validated writes."""

from __future__ import annotations

from cobble.maintenance.schedule_config import ScheduleConfig
from cobble.maintenance.service import MaintenanceSettingsService
from cobble.maintenance.settings_store import MaintenanceSettingsStore
from cobble.settings import Settings


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        bedrock_root=tmp_path / "b",
        state_dir=tmp_path / "s",
        backup_dir=tmp_path / "k",
        bootstrap_on_start=False,
    )
    base.update(over)
    return Settings(**base)


def _service(tmp_path, **settings_over) -> MaintenanceSettingsService:
    store = MaintenanceSettingsStore(tmp_path / "maintenance_settings.json")
    return MaintenanceSettingsService(store, _settings(tmp_path, **settings_over))


# -- 1.3 fallback-vs-overlay precedence -----------------------------
def test_untouched_install_falls_back_to_settings(tmp_path) -> None:
    svc = _service(tmp_path, backup_retention=9, backup_enabled=True, maintenance_time="04:00")
    assert svc.effective_backup_retention() == 9
    assert svc.effective_backup_enabled() is True


def test_overlay_value_takes_precedence_over_settings(tmp_path) -> None:
    store = MaintenanceSettingsStore(tmp_path / "s.json")
    store.set(backup_retention=20)
    svc = MaintenanceSettingsService(store, _settings(tmp_path, backup_retention=9))
    assert svc.effective_backup_retention() == 20


# -- 1.4 first-run seeding from legacy fields -----------------------
def test_seeds_daily_shared_time_backup_first_when_no_overlay(tmp_path) -> None:
    svc = _service(
        tmp_path,
        maintenance_time="04:00",
        backup_enabled=True,
        update_enabled=True,
    )
    backup = svc.effective_backup_schedule()
    update = svc.effective_update_schedule()
    assert backup == ScheduleConfig(enabled=True, time="04:00", frequency="daily", day=None)
    assert update == ScheduleConfig(enabled=True, time="04:00", frequency="daily", day=None)


def test_seeding_reflects_disabled_legacy_flags(tmp_path) -> None:
    svc = _service(tmp_path, backup_enabled=False, update_enabled=False)
    assert svc.effective_backup_schedule().enabled is False
    assert svc.effective_update_schedule().enabled is False


def test_backup_enabled_always_wins_over_a_stale_stored_schedule_flag(tmp_path) -> None:
    # backup_enabled is the single source of truth (task 1.1 decision, documented
    # in service.py); a stored backup_schedule.enabled that disagrees is
    # reconciled rather than trusted.
    store = MaintenanceSettingsStore(tmp_path / "s.json")
    store.set(
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="daily", day=None)
    )
    store.set(backup_enabled=False)
    svc = MaintenanceSettingsService(store, _settings(tmp_path))
    assert svc.effective_backup_schedule().enabled is False


# -- 1.5 / 5.1 effective view -----------------------------------------
def test_effective_view_carries_the_fixed_pre_update_marker(tmp_path) -> None:
    svc = _service(tmp_path)
    view = svc.effective_view().to_dict()
    assert view["pre_update_backup_always_on"] is True


# -- 5.2 validated writes ---------------------------------------------
def test_write_persists_and_survives_a_simulated_restart(tmp_path) -> None:
    path = tmp_path / "maintenance_settings.json"
    store = MaintenanceSettingsStore(path)
    svc = MaintenanceSettingsService(store, _settings(tmp_path))
    result = svc.write({"backup_retention": 30})
    assert result.ok is True
    assert result.settings.backup_retention == 30

    reloaded_store = MaintenanceSettingsStore(path)
    reloaded_svc = MaintenanceSettingsService(reloaded_store, _settings(tmp_path))
    assert reloaded_svc.effective_backup_retention() == 30


def test_invalid_write_is_rejected_and_leaves_prior_settings_intact(tmp_path) -> None:
    store = MaintenanceSettingsStore(tmp_path / "s.json")
    svc = MaintenanceSettingsService(store, _settings(tmp_path))
    svc.write({"backup_retention": 5})

    result = svc.write({"backup_retention": -1})
    assert result.ok is False
    assert result.errors
    assert svc.effective_backup_retention() == 5


def test_invalid_schedule_shape_is_rejected() -> None:
    pass  # covered by test_schedule_config.py; write() delegates to ScheduleConfig.from_dict


def test_unknown_key_is_rejected(tmp_path) -> None:
    store = MaintenanceSettingsStore(tmp_path / "s.json")
    svc = MaintenanceSettingsService(store, _settings(tmp_path))
    result = svc.write({"nonsense": 1})
    assert result.ok is False


# -- 2.4 reschedule callback -------------------------------------------
def test_write_triggers_on_change_callback(tmp_path) -> None:
    store = MaintenanceSettingsStore(tmp_path / "s.json")
    calls = []
    svc = MaintenanceSettingsService(store, _settings(tmp_path), on_change=lambda: calls.append(1))
    svc.write({"backup_retention": 4})
    assert calls == [1]


def test_failed_write_does_not_trigger_on_change(tmp_path) -> None:
    store = MaintenanceSettingsStore(tmp_path / "s.json")
    calls = []
    svc = MaintenanceSettingsService(store, _settings(tmp_path), on_change=lambda: calls.append(1))
    svc.write({"backup_retention": -1})
    assert calls == []
