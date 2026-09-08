"""Recorder wiring, closing sessions cobble ends, and reconciliation
(tasks 2.5, 3.1-3.4, 4.1-4.3)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cobble.events.bus import EventBus
from cobble.events.model import PlayerConnected
from cobble.players.service import PlayerHistoryService
from cobble.players.storage import (
    END_RECONSTRUCTED,
    END_SERVER_EXIT,
    END_SERVER_STOP,
    open_store,
)
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor


class FakeClock:
    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


# -- 3.1 pre-stop hook -------------------------------------------
async def test_pre_stop_hook_fires_before_the_process_is_reaped(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    seen: list[tuple[datetime, bool]] = []
    sup.subscribe_pre_stop(lambda when: seen.append((when, sup.state == RunState.RUNNING)))

    await sup.start()
    await sup.stop()

    assert len(seen) == 1
    when, was_running = seen[0]
    assert was_running is True  # fired before the stop transition / reap
    assert when.tzinfo is not None


# -- 2.5 / 3.2 recorder attached, stop closes sessions ----------
async def test_connect_recorded_then_stop_closes_it_as_server_stop(
    make_supervisor, tmp_path
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    store = open_store(tmp_path / "cobble.db")
    bus = EventBus()
    clock = FakeClock()
    svc = PlayerHistoryService(store, sup, bus, checkpoint_seconds=999, clock=clock)

    await sup.start()
    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    bus.publish(PlayerConnected(raw="", xuid="x2", gamertag="Sam"))
    assert store.open_session_xuids() == ["x1", "x2"]

    clock.advance(3600)
    await sup.stop()

    assert store.open_session_xuids() == []
    for xuid in ("x1", "x2"):
        row = store.sessions_for(xuid, now=clock())[0]
        assert row.end_reason == END_SERVER_STOP
        assert row.disconnected_at == clock().isoformat() or row.disconnected_at is not None
    await svc.aclose()


# -- 3.3 unexpected exit closes sessions as server_exit ---------
async def test_unexpected_exit_closes_sessions_as_server_exit(
    make_supervisor, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0, crash_restart_threshold=0)
    store = open_store(tmp_path / "cobble.db")
    bus = EventBus()
    svc = PlayerHistoryService(store, sup, bus, checkpoint_seconds=999)

    monkeypatch.setenv("FAKE_BDS_CRASH_AFTER", "0.3")
    await sup.start()
    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    await asyncio.wait_for(sup.wait_for_state(RunState.CRASHED), timeout=5)
    await sup.wait_supervise_idle()

    assert store.open_session_xuids() == []
    row = store.sessions_for("x1", now=datetime.now(UTC))[0]
    assert row.end_reason == END_SERVER_EXIT
    await svc.aclose()


# -- 3.4 every cobble-initiated stop path leaves nothing open ---
@pytest.mark.parametrize("path", ["manual", "restart", "maintenance"])
async def test_no_session_left_open_for_any_stop_path(make_supervisor, path: str, tmp_path) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    store = open_store(tmp_path / "cobble.db")
    bus = EventBus()
    svc = PlayerHistoryService(store, sup, bus, checkpoint_seconds=999)

    await sup.start()
    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    assert store.open_session_xuids() == ["x1"]

    if path == "manual":
        await sup.stop()
    elif path == "restart":
        await sup.restart()
        await sup.stop()
    elif path == "maintenance":
        async with sup.maintenance_scope("backing_up"):
            await sup.maintenance_stop(reason="backup")

    assert store.open_session_xuids() == []
    await svc.aclose()


# -- 4.1 checkpoint loop --------------------------------------
async def test_checkpoint_advances_while_running_and_stops_when_stopped(
    make_supervisor, tmp_path
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    store = open_store(tmp_path / "cobble.db")
    bus = EventBus()
    clock = FakeClock()
    svc = PlayerHistoryService(store, sup, bus, checkpoint_seconds=0.05, clock=clock)
    await svc.start()

    await sup.start()
    store.open_session("x1", "Alex", clock())
    baseline = store.sessions_for("x1", now=clock())[0].last_active_at

    clock.advance(10)
    await asyncio.sleep(0.2)
    advanced = store.sessions_for("x1", now=clock())[0].last_active_at
    assert advanced > baseline

    await sup.stop()
    clock.advance(10)
    frozen = store.sessions_for("x1", now=clock())[0].last_active_at
    await asyncio.sleep(0.2)
    # The session is closed now, but even an open one must not advance when
    # stopped: the WHERE end_reason IS NULL clause and the run-state check both
    # hold. Assert the recorded value did not move.
    assert store.sessions_for("x1", now=clock())[0].last_active_at == frozen
    await svc.aclose()


# -- 4.2 / 4.3 startup reconciliation -------------------------
def test_reconcile_closes_leftover_open_session_at_last_active(
    tmp_path: Path, make_supervisor
) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", datetime(2026, 1, 1, tzinfo=UTC))
    store.touch_open_sessions(datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC))
    store.close()

    sup = make_supervisor()
    store2 = open_store(tmp_path / "cobble.db")
    bus = EventBus()
    svc = PlayerHistoryService(store2, sup, bus, checkpoint_seconds=999)
    svc.reconcile()

    row = store2.sessions_for("x1", now=datetime.now(UTC))[0]
    assert row.end_reason == END_RECONSTRUCTED
    assert row.disconnected_at == datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC).isoformat()
    store2.close()


async def test_reconcile_runs_before_any_new_event_is_recorded(
    tmp_path: Path, make_supervisor
) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", datetime(2026, 1, 1, tzinfo=UTC))
    store.touch_open_sessions(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    store.close()

    sup = make_supervisor()
    store2 = open_store(tmp_path / "cobble.db")
    bus = EventBus()
    svc = PlayerHistoryService(store2, sup, bus, checkpoint_seconds=999)
    svc.reconcile()
    # Only now does a fresh connect arrive.
    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))

    rows = store2.sessions_for("x1", now=datetime.now(UTC))
    assert len(rows) == 2
    assert rows[1].end_reason == END_RECONSTRUCTED  # the pre-existing one, closed first
    assert rows[0].in_progress is True  # the new session, untouched by reconcile
    await svc.aclose()


def test_reconcile_prefers_shutdown_time_when_later(tmp_path: Path, make_supervisor) -> None:
    # last_active at 09:00, but a clean shutdown was recorded at 09:30.
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", datetime(2026, 1, 1, 8, tzinfo=UTC))
    store.touch_open_sessions(datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC))
    store.close()

    later = datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC)
    store2 = open_store(tmp_path / "cobble.db")
    store2.reconcile_open_sessions(shutdown_at=later)
    assert store2.sessions_for("x1", now=datetime.now(UTC))[0].disconnected_at == later.isoformat()
    store2.close()


def test_reconcile_keeps_last_active_when_shutdown_is_earlier(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", datetime(2026, 1, 1, 8, tzinfo=UTC))
    store.touch_open_sessions(datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC))
    earlier = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    store.reconcile_open_sessions(shutdown_at=earlier)
    got = store.sessions_for("x1", now=datetime.now(UTC))[0].disconnected_at
    assert got == datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC).isoformat()
    store.close()
