"""Tasks 7.1-7.4."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cobble.api._shared import auth_guard
from cobble.app import create_app
from cobble.settings import Settings

STATE_CHANGING = [
    ("post", "/api/server/start"),
    ("post", "/api/server/stop"),
    ("post", "/api/server/restart"),
    ("post", "/api/console/command"),
]
READ_ONLY = [
    ("get", "/api/status"),
]


@pytest.fixture
def app_settings(install_fake_bedrock) -> Settings:
    return install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        yield c


# -- 7.1 API surface ------------------------------------------------
def test_openapi_lists_every_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for expected in (
        "/api/server/start",
        "/api/server/stop",
        "/api/server/restart",
        "/api/console/stream",
        "/api/console/command",
        "/api/status",
        "/api/status/stream",
    ):
        assert expected in paths, f"{expected} missing from OpenAPI schema"


def test_single_auth_seam_covers_all_state_changing_routes(app_settings: Settings) -> None:
    app = create_app(app_settings)

    def deny() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="denied")

    app.dependency_overrides[auth_guard] = deny
    with TestClient(app) as c:
        for method, path in STATE_CHANGING:
            resp = getattr(c, method)(path, json={"command": "list"})
            assert resp.status_code == 401, f"{path} not behind auth_guard"
        for method, path in READ_ONLY:
            assert getattr(c, method)(path).status_code == 200


# -- 7.2 lifecycle errors ---------------------------------------
def test_invalid_transitions_return_distinguishable_errors(client: TestClient) -> None:
    # already running
    assert client.post("/api/server/start").status_code == 200
    dup = client.post("/api/server/start")
    assert dup.status_code == 409
    assert dup.json()["detail"]["error"] == "already_running"
    client.post("/api/server/stop")


def test_start_without_installation_returns_no_installation(tmp_settings: Settings) -> None:
    with TestClient(create_app(tmp_settings)) as c:
        resp = c.post("/api/server/start")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "no_installation"


def test_command_when_not_running_returns_not_running(client: TestClient) -> None:
    resp = client.post("/api/console/command", json={"command": "list"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "not_running"


# -- 7.3 streams + command ------------------------------------
async def test_sse_response_emits_prelude_then_json_data_frames() -> None:
    # The infinite SSE endpoints (/api/console/stream, /api/status/stream) are
    # exercised end-to-end at the Console / StatusTracker level; here we verify
    # the HTTP framing the routes wrap them in.
    from cobble.api._shared import sse_response

    async def events():
        yield {"n": 1}
        yield {"n": 2}

    class FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    resp = sse_response(events(), FakeRequest())  # type: ignore[arg-type]
    assert resp.media_type == "text/event-stream"

    chunks: list[bytes] = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    body = b"".join(chunks).decode()
    assert body.startswith(": connected\n\n")
    assert 'data: {"n": 1}\n\n' in body
    assert 'data: {"n": 2}\n\n' in body


def test_status_get_reflects_lifecycle(client: TestClient) -> None:
    assert client.get("/api/status").json()["run_state"] == "stopped"
    client.post("/api/server/start")
    body = client.get("/api/status").json()
    assert body["run_state"] == "running"
    assert body["version"] == "1.2.3.4"
    assert body["uptime_seconds"] is not None
    client.post("/api/server/stop")
    assert client.get("/api/status").json()["run_state"] == "stopped"


# -- 7.4 no capability outside the API ------------------------
def test_every_action_works_for_a_plain_non_browser_client(client: TestClient) -> None:
    # No Origin/Referer/Sec-Fetch headers, no cookies: a bare programmatic client.
    assert client.post("/api/server/start").json()["run_state"] in {"starting", "running"}
    assert client.get("/api/status").json()["run_state"] in {"starting", "running"}
    assert client.post("/api/console/command", json={"command": "list"}).status_code == 204
    assert client.post("/api/server/restart").json()["run_state"] == "running"
    assert client.post("/api/server/stop").json()["run_state"] == "stopped"
