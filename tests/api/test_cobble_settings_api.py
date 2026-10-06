"""cobble-settings: GET/PUT /api/cobble/settings."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from cobble.api._shared import auth_guard
from cobble.app import create_app
from cobble.settings import Settings


@pytest.fixture
def app_settings(install_fake_bedrock, monkeypatch) -> Settings:
    monkeypatch.setenv("TZ", "UTC")  # the host zone
    return install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        yield c


def test_get_with_the_zone_unset(client: TestClient) -> None:
    body = client.get("/api/cobble/settings").json()
    assert body["timezone"] is None
    assert body["host_timezone"] == "UTC"
    assert body["effective_timezone"] == "UTC"
    assert body["effective_offset"] == "+00:00"
    assert "Australia/Brisbane" in body["timezones"]
    assert "UTC" in body["timezones"]


def test_put_a_valid_name_saves_and_reports_it(client: TestClient, app_settings: Settings) -> None:
    resp = client.put("/api/cobble/settings", json={"timezone": "Australia/Brisbane"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["timezone"] == "Australia/Brisbane"
    assert body["host_timezone"] == "UTC"
    assert body["effective_timezone"] == "Australia/Brisbane"
    assert body["effective_offset"] == "+10:00"

    assert client.get("/api/cobble/settings").json()["timezone"] == "Australia/Brisbane"
    saved = json.loads((app_settings.state_dir / "cobble_settings.json").read_text())
    assert saved == {"timezone": "Australia/Brisbane"}


def test_put_null_returns_to_the_host_default(client: TestClient) -> None:
    client.put("/api/cobble/settings", json={"timezone": "Australia/Brisbane"})
    resp = client.put("/api/cobble/settings", json={"timezone": None})
    assert resp.status_code == 200
    body = resp.json()
    assert body["timezone"] is None
    assert body["effective_timezone"] == "UTC"


def test_put_an_unknown_name_is_422_and_leaves_the_value_unchanged(client: TestClient) -> None:
    client.put("/api/cobble/settings", json={"timezone": "Europe/London"})
    resp = client.put("/api/cobble/settings", json={"timezone": "Mars/Olympus_Mons"})
    assert resp.status_code == 422
    assert "not recognised" in resp.json()["detail"]
    assert client.get("/api/cobble/settings").json()["timezone"] == "Europe/London"


def test_put_pushes_a_status_update(client: TestClient) -> None:
    runtime = client.app.state.runtime
    pushed: list[int] = []
    runtime.status.notify = lambda: pushed.append(1)
    client.put("/api/cobble/settings", json={"timezone": "Australia/Brisbane"})
    assert pushed == [1]


def test_changing_the_zone_changes_the_next_run_without_a_restart(client: TestClient) -> None:
    runtime = client.app.state.runtime
    client.post(
        "/api/maintenance/settings",
        json={
            "changes": {"backup_schedule": {"enabled": True, "time": "04:00", "frequency": "daily"}}
        },
    )
    before = runtime.scheduler.backup_next_run()
    assert before.hour == 4  # the host zone is UTC

    client.put("/api/cobble/settings", json={"timezone": "Australia/Brisbane"})
    after = runtime.scheduler.backup_next_run()
    assert after != before
    assert after.hour == 18  # 04:00 Brisbane is 18:00 UTC the previous day
    status = client.get("/api/status").json()
    assert status["backup"]["next_scheduled_at"].endswith("T04:00:00+10:00")


def test_the_settings_routes_are_behind_the_auth_guard(app_settings: Settings) -> None:
    app = create_app(app_settings)

    def deny() -> None:
        raise HTTPException(status_code=401, detail="denied")

    app.dependency_overrides[auth_guard] = deny
    with TestClient(app) as c:
        assert c.get("/api/cobble/settings").status_code == 401
        assert c.put("/api/cobble/settings", json={"timezone": "UTC"}).status_code == 401
