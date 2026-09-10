"""Section 5: the /api/import router — upload, inspect, discard, apply."""

from __future__ import annotations

import tracemalloc

import pytest
from fastapi.testclient import TestClient

from cobble.api._shared import auth_guard
from cobble.app import create_app
from cobble.settings import Settings

from ..worldimport._fixtures import build_zip, make_level_dat, world_members


@pytest.fixture
def app_settings(install_fake_bedrock) -> Settings:
    return install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0, readiness_timeout=5.0)


@pytest.fixture
def client(app_settings: Settings):
    with TestClient(create_app(app_settings)) as c:
        yield c


def _archive_bytes(version=(1, 2, 3, 4)) -> bytes:
    members = world_members("worlds/W/", level_dat=make_level_dat(version=list(version)))
    members["worlds/W/imported-marker"] = b"IMPORTED"
    return build_zip(members)


def _seed_current_world(runtime) -> None:
    layout = runtime.layout
    (layout.data_dir / "worlds" / "Bedrock level").mkdir(parents=True, exist_ok=True)
    (layout.data_dir / "worlds" / "Bedrock level" / "marker").write_bytes(b"orig")
    (layout.data_dir / "server.properties").write_text("level-name=Bedrock level\n")


# -- 5.5 OpenAPI surface -----------------------------------------
def test_openapi_lists_the_four_import_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/import" in paths
    assert "/api/import/upload" in paths
    assert "/api/import/apply" in paths
    assert {"get", "delete"} <= set(paths["/api/import"])
    assert "post" in paths["/api/import/upload"]
    assert "post" in paths["/api/import/apply"]


# -- 5.1 every route is behind auth_guard ------------------------
def test_every_import_route_requires_auth(app_settings: Settings) -> None:
    app = create_app(app_settings)

    def deny() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="denied")

    app.dependency_overrides[auth_guard] = deny
    with TestClient(app) as c:
        assert c.get("/api/import").status_code == 401
        assert c.delete("/api/import").status_code == 401
        assert c.post("/api/import/upload", content=b"x").status_code == 401
        assert c.post("/api/import/apply", json={}).status_code == 401


# -- 5.3 GET / DELETE with and without an archive held ----------
def test_get_reports_empty_state_when_nothing_is_held(client: TestClient) -> None:
    body = client.get("/api/import").json()
    assert body["held"] is False and body["inspection"] is None


def test_get_describes_a_held_archive_and_delete_discards_it(client: TestClient) -> None:
    up = client.post("/api/import/upload", content=_archive_bytes())
    assert up.status_code == 200
    body = client.get("/api/import").json()
    assert body["held"] is True
    assert body["inspection"]["world_prefix"] == "worlds/W/"
    assert body["version"]["relation"] == "same"

    assert client.delete("/api/import").json()["held"] is False
    assert client.get("/api/import").json()["held"] is False


# -- 5.2 the upload is streamed, not buffered ------------------
async def test_receive_upload_memory_does_not_scale_with_body(client: TestClient) -> None:
    runtime = client.app.state.runtime
    chunk = b"\xa5" * (1 << 20)
    total_mib = 200

    async def body():
        for _ in range(total_mib):
            yield chunk

    tracemalloc.start()
    try:
        await runtime.imports.receive_upload(body(), declared_size=None)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # The staged file is 200 MiB on disk; Python peak stays a small multiple of
    # the chunk size, nowhere near the body size.
    assert peak < 32 * (1 << 20), f"peak {peak} scaled with the body"
    assert runtime.imports.slot.archive_path.stat().st_size == total_mib * (1 << 20)
    runtime.imports.discard()


# -- 5.4 apply: success -------------------------------------
def test_apply_success_returns_a_restore_shaped_outcome(client: TestClient) -> None:
    runtime = client.app.state.runtime
    _seed_current_world(runtime)
    client.post("/api/import/upload", content=_archive_bytes())

    body = client.post("/api/import/apply", json={}).json()
    assert body["ok"] is True
    assert body["world"] == "Bedrock level"
    assert body["replaced_capture"]
    assert {
        "ok",
        "at",
        "world",
        "replaced_capture",
        "needs_confirmation",
        "warning",
        "error",
    } == set(body)
    dest = runtime.layout.data_dir / "worlds" / "Bedrock level"
    assert (dest / "imported-marker").read_bytes() == b"IMPORTED"


# -- 5.4 apply: needs confirmation for an older world -----------
def test_apply_older_world_needs_confirmation_then_proceeds(client: TestClient) -> None:
    runtime = client.app.state.runtime
    _seed_current_world(runtime)
    client.post("/api/import/upload", content=_archive_bytes(version=(1, 0, 0, 0)))

    first = client.post("/api/import/apply", json={}).json()
    assert first["ok"] is False and first["needs_confirmation"] is True
    assert "older" in first["warning"]

    # still held, nothing applied
    assert client.get("/api/import").json()["held"] is True

    confirmed = client.post("/api/import/apply", json={"confirm_old_version": True}).json()
    assert confirmed["ok"] is True


# -- 5.4 apply: a newer world is refused, not overridable ------
def test_apply_newer_world_is_refused_even_with_confirmation(client: TestClient) -> None:
    runtime = client.app.state.runtime
    _seed_current_world(runtime)
    client.post("/api/import/upload", content=_archive_bytes(version=(9, 0, 0, 0)))

    body = client.post("/api/import/apply", json={"confirm_old_version": True}).json()
    assert body["ok"] is False
    assert body["needs_confirmation"] is False
    assert "1.2.3.4" in body["error"] and "9.0.0.0" in body["error"]


# -- 5.4 apply: conflicting-operation rejection ---------------
def test_apply_during_another_maintenance_op_is_a_409(client: TestClient) -> None:
    runtime = client.app.state.runtime
    _seed_current_world(runtime)
    client.post("/api/import/upload", content=_archive_bytes())

    runtime.supervisor._maintenance = "backing_up"
    try:
        resp = client.post("/api/import/apply", json={})
    finally:
        runtime.supervisor._maintenance = None
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "maintenance_conflict"
