"""Gamerule HTTP routes (tasks 5.1-5.6)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from cobble.api._shared import auth_guard
from cobble.api.gamerules import build_gamerules_router
from cobble.gamerules.storage import REPORT_ADOPTION, Report
from tests.gamerules.conftest import FIXED_NOW


class FakeRuntime:
    def __init__(self, manager) -> None:
        self.gamerules = manager


def _client(manager, *, deny_auth: bool = False) -> TestClient:
    app = FastAPI()
    app.include_router(build_gamerules_router(FakeRuntime(manager)), prefix="/api")
    if deny_auth:
        app.dependency_overrides[auth_guard] = lambda: (_ for _ in ()).throw(
            HTTPException(status_code=401, detail="denied")
        )
    return TestClient(app)


# -- 5.1 GET /api/gamerules --------------------------------------
def test_read_shape_for_a_running_server(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True, "randomTickSpeed": 1, "futureRule": "x"})
    body = _client(env.mgr).get("/api/gamerules").json()
    assert body["liveness"] == "live"
    assert body["level_name"] == "world-a"
    by = {r["name"]: r for r in body["rules"]}
    assert by["mobGriefing"]["type"] == "bool"
    assert by["mobGriefing"]["recognised"] is True
    assert by["randomTickSpeed"]["maximum"] == 4096
    assert by["futureRule"]["recognised"] is False


def test_read_shape_for_a_stopped_server_with_a_record(make_manager) -> None:
    env = make_manager(values={"mobGriefing": False})
    env.store.write_record("world-a", {"mobGriefing": False}, FIXED_NOW)
    env.sup.set_running(False)
    body = _client(env.mgr).get("/api/gamerules").json()
    assert body["liveness"] == "recorded"
    assert body["sampled_at"] == FIXED_NOW.isoformat()
    assert body["rules"][0]["name"] == "mobGriefing"


def test_read_shape_for_an_unread_world(make_manager) -> None:
    env = make_manager(running=False)
    body = _client(env.mgr).get("/api/gamerules").json()
    assert body["liveness"] == "unread"
    assert body["rules"] == []


# -- 5.2 the write route ---------------------------------------
def test_write_returns_the_reread_value(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True})
    r = _client(env.mgr).post("/api/gamerules", json={"name": "mobGriefing", "value": False})
    assert r.status_code == 200
    body = r.json()
    assert body["queued"] is False
    assert body["rule"]["name"] == "mobGriefing"
    assert body["rule"]["value"] is False  # from the re-read set


def test_write_refusal_returns_a_per_rule_reason(make_manager) -> None:
    env = make_manager(values={"randomTickSpeed": 1})
    r = _client(env.mgr).post(
        "/api/gamerules", json={"name": "randomTickSpeed", "value": 99999}
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["rule"] == "randomTickSpeed"
    assert "range" in detail["detail"] or "4096" in detail["detail"]


def test_write_route_is_behind_auth_guard(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True})
    r = _client(env.mgr, deny_auth=True).post(
        "/api/gamerules", json={"name": "mobGriefing", "value": False}
    )
    assert r.status_code == 401


# -- 5.3 preferred defaults ----------------------------------
def test_defaults_set_read_and_clear(make_manager) -> None:
    env = make_manager()
    c = _client(env.mgr)
    assert c.get("/api/gamerules/defaults").json()["defaults"] == {}

    c.put("/api/gamerules/defaults", json={"name": "keepInventory", "value": True})
    c.put("/api/gamerules/defaults", json={"name": "randomTickSpeed", "value": 3})
    assert c.get("/api/gamerules/defaults").json()["defaults"] == {
        "keepInventory": True,
        "randomTickSpeed": 3,
    }

    c.delete("/api/gamerules/defaults/keepInventory")
    assert c.get("/api/gamerules/defaults").json()["defaults"] == {"randomTickSpeed": 3}


def test_defaults_reject_a_bad_value(make_manager) -> None:
    env = make_manager()
    r = _client(env.mgr).put(
        "/api/gamerules/defaults", json={"name": "randomTickSpeed", "value": -5}
    )
    assert r.status_code == 409


# -- 5.4 the acknowledge route ------------------------------
def test_acknowledge_clears_the_report_without_touching_the_record(make_manager) -> None:
    env = make_manager(values={"mobGriefing": False})
    env.store.write_record("world-a", {"mobGriefing": False}, FIXED_NOW)
    env.store.write_report(
        Report("world-a", REPORT_ADOPTION, FIXED_NOW.isoformat(), {"mobGriefing": False})
    )
    c = _client(env.mgr)
    assert c.post("/api/gamerules/acknowledge").json() == {"ok": True}
    assert env.mgr.status_block()["report"] is None
    assert env.store.read_record("world-a").values == {"mobGriefing": False}  # untouched


# -- 5.5 a write while the server is stopped is queued -----
async def test_stopped_write_is_queued_and_applied_at_next_start(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True}, running=False)
    r = _client(env.mgr).post(
        "/api/gamerules", json={"name": "mobGriefing", "value": False}
    )
    body = r.json()
    assert body["queued"] is True
    assert body["pending"] == {"mobGriefing": False}
    assert env.svc.writes == []  # no command issued
    assert env.store.read_pending("world-a") == {"mobGriefing": False}

    # the following readiness applies it
    env.sup.set_running(True)
    await env.mgr.reconcile()
    assert ("mobGriefing", False) in env.svc.writes
    assert env.store.read_pending("world-a") == {}  # consumed


# -- 5.6 the status block ----------------------------------
def test_status_block_shape(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True})
    block = env.mgr.status_block()
    assert block["active_world"] == "world-a"
    assert block["liveness"] == "live"
    assert "last_read_at" in block
    assert block["report"] is None


async def test_a_recorded_report_notifies_the_status_stream(make_manager) -> None:
    calls: list[int] = []
    env = make_manager(values={"mobGriefing": False}, on_report=lambda: calls.append(1))
    env.store.write_record("world-a", {"mobGriefing": True}, FIXED_NOW)
    await env.mgr.reconcile()  # an adoption records a report
    assert calls  # on_report fired → status.notify() would push a stream event
    assert env.mgr.status_block()["report"]["kind"] == "adoption"
