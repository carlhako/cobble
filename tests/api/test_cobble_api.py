"""cobble-self-update 4.1: the /api/cobble routes."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from cobble.app import create_app
from cobble.selfupdate.release_check import ReleaseCheckState
from cobble.settings import Settings

RELEASE_URL = "https://github.com/carlhako/cobble/releases/tag/v0.5.0"


@pytest.fixture
def app_settings(install_fake_bedrock) -> Settings:
    return install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        runtime = c.app.state.runtime
        runtime.release_check.current = "0.4.0"
        runtime.upgrade.current = "0.4.0"
        runtime.upgrade._poll = 0.01
        yield c


def _available(client: TestClient, latest: str = "0.5.0") -> None:
    client.app.state.runtime.release_check._state = ReleaseCheckState(
        latest=latest,
        tag=f"v{latest}",
        release_url=RELEASE_URL,
        name=f"cobble {latest}",
        published_at="2026-09-24T00:17:27Z",
        notes="- new things",
        checked_at="T",
    )


def _install_helper(settings: Settings) -> None:
    settings.upgrade_helper_path.parent.mkdir(parents=True, exist_ok=True)
    settings.upgrade_helper_path.write_text("#!/usr/bin/python3\n")
    settings.upgrade_status_dir.mkdir(parents=True, exist_ok=True)


def test_routes_are_registered(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for route in ("/api/cobble/version", "/api/cobble/check", "/api/cobble/upgrade"):
        assert route in paths


def test_version_shape_before_any_check(client: TestClient) -> None:
    body = client.get("/api/cobble/version").json()
    assert body == {
        "current": "0.4.0",
        "latest": None,
        "update_available": False,
        "release_url": None,
        "release_name": None,
        "published_at": None,
        "notes": None,
        "checked_at": None,
        "check_error": None,
        "one_click_available": False,
        "manual_command": (
            "curl -fsSL https://github.com/carlhako/cobble/releases/latest/download/install.sh"
            " | bash"
        ),
        "upgrade": None,
    }


def test_version_with_update_and_helper(client: TestClient, app_settings: Settings) -> None:
    _available(client)
    _install_helper(app_settings)
    body = client.get("/api/cobble/version").json()
    assert body["update_available"] is True
    assert body["latest"] == "0.5.0"
    assert body["release_url"] == RELEASE_URL
    assert body["release_name"] == "cobble 0.5.0"
    assert body["published_at"] == "2026-09-24T00:17:27Z"
    assert body["notes"] == "- new things"
    assert body["one_click_available"] is True
    assert body["manual_command"] is None


def test_check_contacts_the_release_source(client: TestClient) -> None:
    runtime = client.app.state.runtime
    runtime.release_check._transport = httpx.MockTransport(
        lambda _r: httpx.Response(
            200, json={"tag_name": "v0.5.0", "html_url": RELEASE_URL, "body": "- notes"}
        )
    )
    body = client.post("/api/cobble/check").json()
    assert body["latest"] == "0.5.0" and body["update_available"] is True
    assert body["notes"] == "- notes"


def test_upgrade_is_accepted_and_reported_pending(
    client: TestClient, app_settings: Settings
) -> None:
    _available(client)
    _install_helper(app_settings)
    resp = client.post("/api/cobble/upgrade", json={"version": "0.5.0"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["upgrade"]["state"] == "pending"
    assert body["notes"] == "- new things"
    assert body["upgrade"]["from"] == "0.4.0" and body["upgrade"]["to"] == "0.5.0"
    request = app_settings.upgrade_request_dir / "request.json"
    assert json.loads(request.read_text())["tag"] == "v0.5.0"
    status = client.get("/api/status").json()
    assert status["maintenance"]["operation"] == "cobble_upgrade"

    # A second request while pending is refused.
    again = client.post("/api/cobble/upgrade", json={"version": "0.5.0"})
    assert again.status_code == 409
    assert again.json()["detail"]["error"] == "upgrade_in_progress"


def _code(resp: httpx.Response) -> str:
    assert resp.status_code == 409, resp.text
    return resp.json()["detail"]["error"]


def test_upgrade_refused_without_an_update(client: TestClient, app_settings: Settings) -> None:
    _install_helper(app_settings)
    resp = client.post("/api/cobble/upgrade", json={"version": "0.5.0"})
    assert _code(resp) == "no_update_available"


def test_upgrade_refused_on_mismatch(client: TestClient, app_settings: Settings) -> None:
    _available(client)
    _install_helper(app_settings)
    resp = client.post("/api/cobble/upgrade", json={"version": "0.6.0"})
    assert _code(resp) == "version_mismatch"


def test_upgrade_refused_without_helper(client: TestClient) -> None:
    _available(client)
    resp = client.post("/api/cobble/upgrade", json={"version": "0.5.0"})
    assert _code(resp) == "helper_not_installed"


def test_upgrade_refused_during_maintenance(client: TestClient, app_settings: Settings) -> None:
    _available(client)
    _install_helper(app_settings)
    client.app.state.runtime.supervisor._maintenance = "backing_up"
    try:
        resp = client.post("/api/cobble/upgrade", json={"version": "0.5.0"})
    finally:
        client.app.state.runtime.supervisor._maintenance = None
    assert _code(resp) == "maintenance_conflict"


def test_upgrade_requires_a_version(client: TestClient) -> None:
    assert client.post("/api/cobble/upgrade", json={}).status_code == 422
