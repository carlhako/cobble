"""Player roster HTTP interface (tasks 6.1-6.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from cobble.app import create_app
from cobble.players.storage import END_OBSERVED, END_RECONSTRUCTED
from cobble.settings import Settings


@pytest.fixture
def app_settings(install_fake_bedrock) -> Settings:
    return install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        yield c


def _seed(client: TestClient) -> None:
    store = client.app.state.runtime.players
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    # Alex: two closed sessions.
    store.open_session("alex", "Alex", base)
    store.close_session("alex", base + timedelta(hours=1), END_OBSERVED)
    store.open_session("alex", "Alex", base + timedelta(hours=2))
    store.close_session("alex", base + timedelta(hours=3), END_RECONSTRUCTED)
    # Sam: one older, closed session.
    store.open_session("sam", "Sam", base - timedelta(days=1))
    store.close_session("sam", base - timedelta(days=1) + timedelta(minutes=30), END_OBSERVED)


# -- 6.1 roster shape ------------------------------------------
def test_roster_shape_and_fields(client: TestClient) -> None:
    _seed(client)
    body = client.get("/api/players").json()
    assert set(body) == {"players", "recorded_since"}
    alex = next(p for p in body["players"] if p["xuid"] == "alex")
    assert set(alex) == {
        "xuid",
        "gamertag",
        "total_playtime_seconds",
        "session_count",
        "first_seen",
        "last_seen",
        "online",
        "approximate",
    }
    assert alex["gamertag"] == "Alex"
    assert alex["session_count"] == 2
    assert alex["total_playtime_seconds"] == pytest.approx(7200.0)
    assert alex["online"] is False
    assert alex["approximate"] is True  # one session was reconstructed
    # sorted by last seen, most recent first
    assert [p["xuid"] for p in body["players"]] == ["alex", "sam"]


def test_empty_roster_is_200_with_empty_list(client: TestClient) -> None:
    resp = client.get("/api/players")
    assert resp.status_code == 200
    assert resp.json() == {"players": [], "recorded_since": None}


# -- 6.2 per-player sessions ----------------------------------
def test_sessions_ordered_most_recent_first(client: TestClient) -> None:
    _seed(client)
    body = client.get("/api/players/alex/sessions").json()
    assert body["xuid"] == "alex"
    starts = [s["connected_at"] for s in body["sessions"]]
    assert starts == sorted(starts, reverse=True)
    assert body["sessions"][0]["end_reason"] == END_RECONSTRUCTED
    assert body["sessions"][0]["approximate"] is True
    assert body["sessions"][0]["duration_seconds"] == pytest.approx(3600.0)


def test_unknown_identifier_is_404(client: TestClient) -> None:
    resp = client.get("/api/players/nobody/sessions")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "unknown_player"


# -- 6.3 recorded-since present ------------------------------
def test_recorded_since_is_present_on_the_roster(client: TestClient) -> None:
    _seed(client)
    body = client.get("/api/players").json()
    # earliest connect is Sam's, a day before Alex
    assert body["recorded_since"] == datetime(2025, 12, 31, 12, 0, 0, tzinfo=UTC).isoformat()


# -- 6.4 read routes stay unauthenticated -------------------
def test_read_routes_have_no_auth_dependency(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    for path in ("/api/players", "/api/players/{xuid}/sessions"):
        assert path in schema["paths"]
    # consistent with /api/status: a plain GET, 200 without credentials
    assert client.get("/api/players").status_code == 200
