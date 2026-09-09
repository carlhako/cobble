"""Access-control HTTP interface (tasks 7.1-7.5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from cobble.api._shared import auth_guard
from cobble.app import create_app
from cobble.players.storage import END_OBSERVED
from cobble.settings import Settings

STATE_CHANGING = [
    ("post", "/api/access/allowlist", {"name": "X"}),
    ("delete", "/api/access/allowlist?name=X", None),
    ("post", "/api/access/permissions", {"xuid": "x1", "level": "operator"}),
    ("post", "/api/access/enforcement", {"enabled": True}),
    ("post", "/api/players/x1/kick", {}),
    ("post", "/api/players/x1/ban", {}),
    ("post", "/api/players/x1/unban", None),
]


@pytest.fixture
def app_settings(install_fake_bedrock) -> Settings:
    return install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        yield c


def _seed_player(client: TestClient, xuid: str, name: str) -> None:
    store = client.app.state.runtime.players
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    store.open_session(xuid, name, base)
    store.close_session(xuid, base.replace(hour=13), END_OBSERVED)


def _data_dir(client: TestClient):
    return client.app.state.runtime.layout.data_dir


# -- 7.1 read surface ----------------------------------------------
def test_read_shape(client: TestClient) -> None:
    body = client.get("/api/access").json()
    assert set(body) == {"allowlist", "permissions", "enforcement", "bans"}
    assert body["allowlist"] == {"readable": True, "entries": []}
    assert body["permissions"] == []
    assert body["bans"] == []
    assert set(body["enforcement"]) == {"saved", "in_effect", "running", "disagreement"}


def test_read_reports_allowlist_and_permission_entries(client: TestClient) -> None:
    _seed_player(client, "x-alex", "Alex")
    (_data_dir(client) / "allowlist.json").write_text(
        '[{"ignoresPlayerLimit":false,"name":"Alex","xuid":"x-alex"},'
        '{"ignoresPlayerLimit":false,"name":"GhostPlayer"}]'
    )
    (_data_dir(client) / "permissions.json").write_text(
        json.dumps([{"permission": "operator", "xuid": "x-alex"}])
    )
    body = client.get("/api/access").json()
    entries = {e["name"]: e for e in body["allowlist"]["entries"]}
    assert entries["Alex"]["has_identifier"] is True
    assert entries["Alex"]["has_played"] is True
    assert entries["GhostPlayer"]["has_identifier"] is False
    assert entries["GhostPlayer"]["has_played"] is False
    perms = {p["xuid"]: p for p in body["permissions"]}
    assert perms["x-alex"]["level"] == "operator"
    assert perms["x-alex"]["name"] == "Alex"


def test_read_reports_an_unreadable_allowlist(client: TestClient) -> None:
    (_data_dir(client) / "allowlist.json").write_text("{ not json ]")
    body = client.get("/api/access").json()
    assert body["allowlist"]["readable"] is False
    assert body["allowlist"]["entries"] == []


# -- 7.2 every state-changing route is behind auth_guard ----------
def test_state_changing_routes_require_auth(app_settings: Settings) -> None:
    app = create_app(app_settings)

    def deny() -> None:
        raise HTTPException(status_code=401, detail="denied")

    app.dependency_overrides[auth_guard] = deny
    with TestClient(app) as c:
        for method, path, body in STATE_CHANGING:
            resp = (
                getattr(c, method)(path, json=body)
                if body is not None
                else getattr(c, method)(path)
            )
            assert resp.status_code == 401, f"{path} not behind auth_guard"
        assert c.get("/api/access").status_code == 200  # read stays open


# -- 7.3 moderation routes address a player by identifier ---------
def test_ban_route_reaches_the_intended_player(client: TestClient) -> None:
    _seed_player(client, "x-target", "Target")
    # enforcement already saved on, so no confirmation gate; server stopped
    (_data_dir(client) / "server.properties").write_text("allow-list=true\n")
    resp = client.post("/api/players/x-target/ban", json={"reason": "griefing"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["xuid"] == "x-target"
    assert "recorded" in body["steps"]
    assert client.app.state.runtime.ban_store.is_banned("x-target") is True


def test_moderation_route_refuses_an_unknown_identifier(client: TestClient) -> None:
    for path in ("/api/players/nobody/kick", "/api/players/nobody/ban"):
        resp = client.post(path, json={})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "unknown_player"


def test_unban_route_lifts_the_ban(client: TestClient) -> None:
    _seed_player(client, "x-t", "T")
    (_data_dir(client) / "server.properties").write_text("allow-list=true\n")
    client.post("/api/players/x-t/ban", json={})
    resp = client.post("/api/players/x-t/unban")
    assert resp.status_code == 200
    assert client.app.state.runtime.ban_store.is_banned("x-t") is False


# -- 7.4 distinguishable error codes ----------------------------
def test_maintenance_conflict_code(client: TestClient) -> None:
    runtime = client.app.state.runtime
    runtime.supervisor._maintenance = "updating"
    try:
        resp = client.post("/api/access/allowlist", json={"name": "Anyone"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "maintenance_in_progress"
    finally:
        runtime.supervisor._maintenance = None


def test_kick_not_running_code(client: TestClient) -> None:
    _seed_player(client, "x-k", "K")
    resp = client.post("/api/players/x-k/kick", json={})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "not_running"


def test_kick_player_not_connected_code(client: TestClient) -> None:
    _seed_player(client, "x-off", "Off")
    client.post("/api/server/start")
    try:
        resp = client.post("/api/players/x-off/kick", json={})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "player_not_connected"
    finally:
        client.post("/api/server/stop")


def test_invalid_permission_level_code(client: TestClient) -> None:
    _seed_player(client, "x-p", "P")
    resp = client.post("/api/access/permissions", json={"xuid": "x-p", "level": "wizard"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "invalid_permission_level"


# -- 7.5 confirmation-required returns the preview, applies nothing --
def test_ban_confirmation_required_returns_the_exclusion_preview(client: TestClient) -> None:
    _seed_player(client, "x-target", "Target")
    _seed_player(client, "x-kid", "Kid")
    # allow-list off (default) and nobody on the allowlist -> banning turns it on
    resp = client.post("/api/players/x-target/ban", json={"reason": "r"})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "confirmation_required"
    assert "Kid" in detail["would_exclude"]
    assert "Target" not in detail["would_exclude"]
    # nothing was applied
    assert client.app.state.runtime.ban_store.is_banned("x-target") is False


def test_ban_with_confirm_applies(client: TestClient) -> None:
    _seed_player(client, "x-target", "Target")
    _seed_player(client, "x-kid", "Kid")
    resp = client.post(
        "/api/players/x-target/ban",
        json={"reason": "r", "confirm": True, "permit_excluded": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "enforcement_enabled" in body["steps"]
    assert client.app.state.runtime.ban_store.is_banned("x-target") is True
    # Kid was carried onto the allowlist
    allow = json.loads((_data_dir(client) / "allowlist.json").read_text())
    assert any(e["name"] == "Kid" for e in allow)
