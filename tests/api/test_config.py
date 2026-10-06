"""Section 6: configuration HTTP routes (tasks 6.1-6.4)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from cobble.api._shared import auth_guard
from cobble.app import create_app
from cobble.settings import Settings

SAMPLE = (
    "# vendor comment\n"
    "difficulty=easy\n"
    "max-players=10\n"
    "view-distance=32\n"
    "level-name=Bedrock level\n"
    "operator-added-key=kept\n"
)


@pytest.fixture
def app_settings(install_fake_bedrock) -> Settings:
    settings = install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)
    from cobble.acquisition.layout import Layout

    layout = Layout.from_settings(settings)
    (layout.data_dir / "server.properties").write_text(SAMPLE)
    return settings


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        yield c


def test_openapi_lists_the_config_routes_under_api(client: TestClient) -> None:
    # 6.1
    paths = client.get("/openapi.json").json()["paths"]
    for expected in ("/api/config", "/api/config/worlds"):
        assert expected in paths, f"{expected} missing from OpenAPI schema"


def test_config_write_route_is_behind_auth_guard(app_settings: Settings) -> None:
    # 6.1 — same dependency as every other state-changing route
    app = create_app(app_settings)
    app.dependency_overrides[auth_guard] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=401, detail="denied")
    )
    with TestClient(app) as c:
        assert c.post("/api/config", json={"changes": {"difficulty": "hard"}}).status_code == 401


def test_read_route_returns_settings_schema_and_pending_when_stopped(client: TestClient) -> None:
    # 6.2
    body = client.get("/api/config").json()
    settings = {s["key"]: s for s in body["settings"] if s["present"]}
    assert set(settings) == {
        "difficulty",
        "max-players",
        "view-distance",
        "level-name",
        "operator-added-key",
    }
    assert settings["difficulty"]["recognised"] is True
    assert settings["difficulty"]["schema"]["type"] == "enum"
    assert settings["operator-added-key"]["recognised"] is False
    assert settings["operator-added-key"]["schema"] is None
    assert body["pending"] == []


def test_read_route_is_correct_with_the_server_running(client: TestClient) -> None:
    client.post("/api/server/start")
    try:
        client.post("/api/config", json={"changes": {"difficulty": "hard"}})
        body = client.get("/api/config").json()
        pending = {c["key"]: (c["saved"], c["in_effect"]) for c in body["pending"]}
        assert pending == {"difficulty": ("hard", "easy")}
    finally:
        client.post("/api/server/stop")


def test_write_route_reports_per_key_rejections_and_changes_nothing(client: TestClient) -> None:
    # 6.3
    before = client.get("/api/config").json()["settings"]
    resp = client.post(
        "/api/config",
        json={"changes": {"difficulty": "brutal", "max-players": "lots"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert {i["key"] for i in body["errors"]} == {"difficulty", "max-players"}
    assert client.get("/api/config").json()["settings"] == before


def test_write_route_returns_warnings_and_persists(client: TestClient) -> None:
    resp = client.post("/api/config", json={"changes": {"view-distance": "500"}})
    body = resp.json()
    assert body["ok"] is True
    assert [i["key"] for i in body["warnings"]] == ["view-distance"]
    assert {s["key"]: s["value"] for s in client.get("/api/config").json()["settings"]}[
        "view-distance"
    ] == "500"


def test_write_route_returns_the_maintenance_conflict(client: TestClient) -> None:
    runtime = client.app.state.runtime
    runtime.supervisor._maintenance = "updating"  # as an update/restore would hold it
    try:
        before = client.get("/api/config").json()["settings"]
        resp = client.post("/api/config", json={"changes": {"difficulty": "hard"}})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "maintenance_in_progress"
        assert client.get("/api/config").json()["settings"] == before  # unchanged
    finally:
        runtime.supervisor._maintenance = None


def test_worlds_route_lists_marks_current_and_missing(client: TestClient) -> None:
    # 6.4
    runtime = client.app.state.runtime
    worlds_dir = runtime.layout.data_dir / "worlds"
    (worlds_dir / "Bedrock level").mkdir(parents=True, exist_ok=True)
    (worlds_dir / "Creative Flats").mkdir(exist_ok=True)

    body = client.get("/api/config/worlds").json()
    assert [w["name"] for w in body["worlds"]] == ["Bedrock level", "Creative Flats"]
    assert body["current"] == "Bedrock level"
    assert body["current_present"] is True

    client.post("/api/config", json={"changes": {"level-name": "Nowhere"}})
    body = client.get("/api/config/worlds").json()
    assert body["current"] == "Nowhere"
    assert body["current_present"] is False


# -- network-settings (task 4.2) ------------------------------------------------


def test_read_and_write_routes_carry_conflicts(client: TestClient) -> None:
    body = client.get("/api/config").json()
    assert body["conflicts"] == []
    udp = {s["key"]: s for s in body["settings"]}["server-udp-ports"]
    assert udp["present"] is False and udp["value"] == ""

    pinned = client.post(
        "/api/config",
        json={"changes": {"transport": "nethernet", "server-udp-ports": "19140-19159"}},
    ).json()
    assert pinned["ok"] is True and pinned["conflicts"] == [] and pinned["warnings"] == []

    # A max-players write past the range: accepted, with the capacity warning.
    raised = client.post("/api/config", json={"changes": {"max-players": "30"}}).json()
    assert raised["ok"] is True
    assert [i["key"] for i in raised["warnings"]] == ["server-udp-ports"]
    assert [i["key"] for i in raised["conflicts"]] == ["server-udp-ports"]
    assert [i["key"] for i in client.get("/api/config").json()["conflicts"]] == ["server-udp-ports"]


def test_a_malformed_udp_range_is_a_per_key_error(client: TestClient) -> None:
    body = client.post("/api/config", json={"changes": {"server-udp-ports": "abc"}}).json()
    assert body["ok"] is False
    assert [(i["key"], i["severity"]) for i in body["errors"]] == [("server-udp-ports", "error")]
    udp = {s["key"]: s for s in client.get("/api/config").json()["settings"]}["server-udp-ports"]
    assert udp["present"] is False


def test_a_hostname_mapping_flows_through_the_api(client: TestClient) -> None:
    value = "play.example.com:19140-19150:19140-19150"
    saved = client.post(
        "/api/config",
        json={"changes": {"transport": "nethernet", "server-udp-ports": value}},
    ).json()
    assert saved["ok"] is True
    nethernet = client.get("/api/config/network").json()["layouts"]["nethernet"]
    assert nethernet["udp_range"]["address"] == "play.example.com"
    assert {"protocol": "udp", "ports": "19140-19150"} in nethernet["forward"]

    raised = client.post("/api/config", json={"changes": {"max-players": "30"}}).json()
    assert raised["ok"] is True
    assert [i["key"] for i in raised["conflicts"]] == ["server-udp-ports"]


def test_network_route_shape(client: TestClient) -> None:
    assert "/api/config/network" in client.get("/openapi.json").json()["paths"]
    client.post(
        "/api/config",
        json={"changes": {"transport": "nethernet", "server-udp-ports": "19140-19159"}},
    )
    body = client.get("/api/config/network").json()
    assert set(body) == {"transport", "layout", "layouts", "conflicts", "identity"}
    assert body["layout"] == "nethernet"
    assert set(body["layouts"]) == {"nethernet", "raknet"}
    nethernet = body["layouts"]["nethernet"]
    assert set(nethernet) == {"settings", "udp_range", "lan_discovery", "forward", "pin_required"}
    assert nethernet["udp_range"]["form"] == "range"
    assert {"protocol": "udp", "ports": "19140-19159"} in nethernet["forward"]
    assert body["transport"]["saved"] == "nethernet"


# -- server-identity (tasks 3.1, 3.2) -------------------------------------------
def _key(client: TestClient):
    key = client.app.state.runtime.layout.data_dir / "keys" / "server_identity_key.pem"
    return key


def test_network_view_carries_identity_when_stopped_without_a_key(client: TestClient) -> None:
    assert client.get("/api/config/network").json()["identity"] == {
        "saved": False,
        "running": False,
    }


def test_network_view_carries_identity_for_a_running_server(client: TestClient) -> None:
    from cobble.supervisor.state import RunState

    runtime = client.app.state.runtime
    sup = runtime.supervisor
    orig = type(sup).state
    type(sup).state = property(lambda self: RunState.RUNNING)
    try:
        assert client.get("/api/config/network").json()["identity"] == {
            "saved": False,
            "running": True,
        }
        key = _key(client)
        key.parent.mkdir(exist_ok=True)
        key.write_text("PEM")
        assert client.get("/api/config/network").json()["identity"] == {
            "saved": True,
            "running": True,
        }
    finally:
        type(sup).state = orig


class _FakeIdentity:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def state(self):
        from cobble.identity.service import IdentityState

        return IdentityState(saved=False, running=True)

    async def aclose(self) -> None:
        pass

    async def save_running(self):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_identity_save_route_succeeds(client: TestClient) -> None:
    from cobble.identity.service import IdentityState

    client.app.state.runtime.identity = _FakeIdentity(IdentityState(saved=True, running=True))
    resp = client.post("/api/config/network/identity/save")
    assert resp.status_code == 200
    assert resp.json() == {"identity": {"saved": True, "running": True}}


def test_identity_save_route_maps_errors(client: TestClient) -> None:
    from cobble.identity.service import IdentitySaveError
    from cobble.supervisor.supervisor import MaintenanceInProgressError, NotRunningError

    runtime = client.app.state.runtime
    runtime.identity = _FakeIdentity(NotRunningError("the server is not running"))
    resp = client.post("/api/config/network/identity/save")
    assert resp.status_code == 409 and resp.json()["detail"]["error"] == "not_running"

    runtime.identity = _FakeIdentity(
        MaintenanceInProgressError("a backup operation is in progress")
    )
    resp = client.post("/api/config/network/identity/save")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "maintenance_in_progress"

    runtime.identity = _FakeIdentity(IdentitySaveError("Failed to save server identity key to x"))
    resp = client.post("/api/config/network/identity/save")
    assert resp.status_code == 502
    assert "Failed to save" in resp.json()["detail"]["detail"]


def test_identity_save_route_refuses_while_stopped_and_writes_nothing(client: TestClient) -> None:
    resp = client.post("/api/config/network/identity/save")
    assert resp.status_code == 409
    assert not _key(client).exists()


def test_identity_save_route_with_a_key_present_sends_no_command(client: TestClient) -> None:
    from cobble.supervisor.state import RunState

    runtime = client.app.state.runtime
    key = _key(client)
    key.parent.mkdir(exist_ok=True)
    key.write_text("operator key")

    async def boom(*a, **kw):
        raise AssertionError("no console command expected")

    runtime.console.query = boom
    sup = runtime.supervisor
    orig = type(sup).state
    type(sup).state = property(lambda self: RunState.RUNNING)
    try:
        resp = client.post("/api/config/network/identity/save")
    finally:
        type(sup).state = orig
    assert resp.status_code == 200
    assert resp.json()["identity"]["saved"] is True
    assert key.read_text() == "operator key"
