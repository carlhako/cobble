"""Gamerule routes wired into the full app (tasks 5.1, 5.6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cobble.acquisition.layout import Layout
from cobble.app import create_app
from cobble.settings import Settings


@pytest.fixture
def client(install_fake_bedrock):
    settings: Settings = install_fake_bedrock("1.2.3.4", shutdown_timeout=5.0)
    layout = Layout.from_settings(settings)
    (layout.data_dir / "server.properties").write_text("level-name=Bedrock level\n")
    with TestClient(create_app(settings)) as c:
        yield c


def test_gamerule_routes_are_registered_under_api(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for expected in ("/api/gamerules", "/api/gamerules/defaults", "/api/gamerules/acknowledge"):
        assert expected in paths, f"{expected} missing from the OpenAPI schema"


def test_read_reports_unread_for_a_stopped_never_run_world(client: TestClient) -> None:
    body = client.get("/api/gamerules").json()
    assert body["liveness"] == "unread"
    assert body["rules"] == []


def test_status_payload_carries_the_gamerules_block(client: TestClient) -> None:
    block = client.get("/api/status").json()["gamerules"]
    assert block is not None
    assert block["active_world"] == "Bedrock level"
    assert block["liveness"] == "unread"
    assert block["report"] is None


def test_defaults_round_trip_through_the_real_store(client: TestClient) -> None:
    client.put("/api/gamerules/defaults", json={"name": "keepInventory", "value": True})
    assert client.get("/api/gamerules/defaults").json()["defaults"] == {"keepInventory": True}
    client.delete("/api/gamerules/defaults/keepInventory")
    assert client.get("/api/gamerules/defaults").json()["defaults"] == {}
