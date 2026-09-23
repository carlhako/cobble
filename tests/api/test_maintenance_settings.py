"""Section 5: the maintenance settings HTTP routes (tasks 5.1-5.3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cobble.app import create_app
from cobble.maintenance.service import MaintenanceSettingsService
from cobble.maintenance.settings_store import MaintenanceSettingsStore
from cobble.settings import Settings


@pytest.fixture
def app_settings(install_fake_bedrock) -> Settings:
    return install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        yield c


def test_openapi_lists_maintenance_settings_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/maintenance/settings" in paths


# -- 5.1 GET -----------------------------------------------------
def test_get_returns_the_effective_settings_with_the_pre_update_marker(
    client: TestClient,
) -> None:
    resp = client.get("/api/maintenance/settings")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("backup_retention", "backup_enabled", "backup_schedule", "update_schedule"):
        assert key in body
    assert body["pre_update_backup_always_on"] is True


def test_get_matches_todays_daily_shared_time_seed_on_a_fresh_install(client: TestClient) -> None:
    body = client.get("/api/maintenance/settings").json()
    runtime = client.app.state.runtime
    assert body["backup_schedule"]["frequency"] == "daily"
    assert body["backup_schedule"]["time"] == runtime.settings.maintenance_time
    assert body["update_schedule"]["time"] == runtime.settings.maintenance_time


# -- 5.2 / 5.3 valid write persists and survives a simulated restart ----
def test_valid_write_persists_and_survives_a_simulated_restart(client: TestClient) -> None:
    resp = client.post("/api/maintenance/settings", json={"changes": {"backup_retention": 21}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["settings"]["backup_retention"] == 21

    runtime = client.app.state.runtime
    path = runtime.settings.state_dir / "maintenance_settings.json"
    assert path.is_file()

    # Simulate a restart: a fresh store/service pointed at the same file.
    reloaded_store = MaintenanceSettingsStore(path)
    reloaded_service = MaintenanceSettingsService(reloaded_store, runtime.settings)
    assert reloaded_service.effective_backup_retention() == 21


def test_write_updates_the_scheduler_without_a_restart(client: TestClient) -> None:
    runtime = client.app.state.runtime
    before = runtime.scheduler.backup_next_run()
    resp = client.post(
        "/api/maintenance/settings",
        json={
            "changes": {
                "backup_schedule": {
                    "enabled": True,
                    "time": "23:45",
                    "frequency": "daily",
                }
            }
        },
    )
    assert resp.status_code == 200
    after = runtime.scheduler.backup_next_run()
    assert after != before
    assert after.hour == 23 and after.minute == 45


# -- 5.3 invalid write is rejected and leaves prior settings intact ----
def test_invalid_write_is_rejected_and_leaves_prior_settings_intact(client: TestClient) -> None:
    good = client.post("/api/maintenance/settings", json={"changes": {"backup_retention": 5}})
    assert good.json()["ok"] is True

    bad = client.post("/api/maintenance/settings", json={"changes": {"backup_retention": -1}})
    assert bad.status_code == 200  # matches server-config's convention: 200 with ok=False
    assert bad.json()["ok"] is False
    assert bad.json()["errors"]

    still = client.get("/api/maintenance/settings").json()
    assert still["backup_retention"] == 5


def test_invalid_schedule_shape_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/maintenance/settings",
        json={
            "changes": {"backup_schedule": {"enabled": True, "time": "bad", "frequency": "daily"}}
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_invalid_day_of_week_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/maintenance/settings",
        json={
            "changes": {
                "update_schedule": {
                    "enabled": True,
                    "time": "05:00",
                    "frequency": "weekly",
                    "day": 9,
                }
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


# -- 5.3 writes during maintenance are not refused (decision documented
# in cobble/api/maintenance.py) -------------------------------------
def test_write_while_a_backup_is_in_progress_is_not_refused(client: TestClient) -> None:
    runtime = client.app.state.runtime
    runtime.backup._busy = "backup"
    try:
        resp = client.post("/api/maintenance/settings", json={"changes": {"backup_retention": 3}})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
    finally:
        runtime.backup._busy = None
