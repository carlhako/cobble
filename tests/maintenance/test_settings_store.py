"""Section 1: the maintenance settings overlay store (task 1.1, 1.2)."""

from __future__ import annotations

from cobble.maintenance.schedule_config import ScheduleConfig
from cobble.maintenance.settings_store import MaintenanceSettingsStore


def test_round_trip_load_save(tmp_path) -> None:
    path = tmp_path / "maintenance_settings.json"
    store = MaintenanceSettingsStore(path)
    assert store.backup_retention is None
    assert store.backup_schedule is None

    store.set(
        backup_retention=14,
        backup_enabled=False,
        backup_schedule=ScheduleConfig(enabled=True, time="03:30", frequency="weekly", day=2),
        update_schedule=ScheduleConfig(enabled=False, time="05:00", frequency="monthly", day=31),
    )
    assert path.is_file()

    reloaded = MaintenanceSettingsStore(path)
    assert reloaded.backup_retention == 14
    assert reloaded.backup_enabled is False
    assert reloaded.backup_schedule == ScheduleConfig(
        enabled=True, time="03:30", frequency="weekly", day=2
    )
    assert reloaded.update_schedule == ScheduleConfig(
        enabled=False, time="05:00", frequency="monthly", day=31
    )


def test_partial_write_leaves_other_fields_untouched(tmp_path) -> None:
    store = MaintenanceSettingsStore(tmp_path / "s.json")
    store.set(backup_retention=5)
    store.set(backup_enabled=True)
    assert store.backup_retention == 5
    assert store.backup_enabled is True


def test_missing_file_yields_all_unset(tmp_path) -> None:
    store = MaintenanceSettingsStore(tmp_path / "does-not-exist.json")
    assert store.backup_retention is None
    assert store.backup_enabled is None
    assert store.backup_schedule is None
    assert store.update_schedule is None


def test_malformed_file_falls_back_to_unset(tmp_path) -> None:
    path = tmp_path / "s.json"
    path.write_text("{not json")
    store = MaintenanceSettingsStore(path)
    assert store.backup_retention is None


def test_malformed_schedule_in_file_falls_back_to_unset(tmp_path) -> None:
    path = tmp_path / "s.json"
    path.write_text('{"backup_schedule": {"enabled": true, "time": "bad", "frequency": "daily"}}')
    store = MaintenanceSettingsStore(path)
    assert store.backup_schedule is None


def test_no_temp_file_left_behind(tmp_path) -> None:
    path = tmp_path / "s.json"
    store = MaintenanceSettingsStore(path)
    store.set(backup_retention=3)
    assert not path.with_suffix(".tmp").exists()
