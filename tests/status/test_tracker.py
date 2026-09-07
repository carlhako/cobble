"""Tasks 6.1-6.4."""

from __future__ import annotations

import asyncio

from cobble.events.model import PlayerConnected, PlayerDisconnected, PlayerSpawned
from cobble.settings import Settings
from cobble.status.tracker import StatusTracker
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor


# -- 6.1 derived status --------------------------------------------
async def test_uptime_absent_when_stopped_present_when_running_resets_on_restart(
    make_supervisor,
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    tracker = StatusTracker(sup)
    assert tracker.snapshot().uptime_seconds is None

    await sup.start()
    await asyncio.sleep(0.2)
    first = tracker.snapshot().uptime_seconds
    assert first is not None and first > 0

    await sup.restart()
    await asyncio.sleep(0.05)
    after_restart = tracker.snapshot().uptime_seconds
    assert after_restart is not None and after_restart < first  # measured from new readiness

    await sup.stop()
    assert tracker.snapshot().uptime_seconds is None


async def test_version_reported_and_none_when_absent(
    tmp_settings: Settings, make_supervisor
) -> None:
    bare = Supervisor(tmp_settings)
    assert StatusTracker(bare).snapshot().version is None

    sup: Supervisor = make_supervisor("1.42.0.7")
    assert StatusTracker(sup).snapshot().version == "1.42.0.7"


async def test_last_shutdown_cleanliness_visible(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    tracker = StatusTracker(sup)
    await sup.start()
    await sup.stop()
    snap = tracker.snapshot()
    assert snap.last_shutdown is not None and snap.last_shutdown.clean is True


# -- 6.2 online players -----------------------------------------
async def test_join_and_leave_update_online_set_and_stop_empties_it(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    tracker = StatusTracker(sup)
    await sup.start()

    tracker.on_event(PlayerConnected(raw="", xuid="100", gamertag="Alex"))
    tracker.on_event(PlayerConnected(raw="", xuid="200", gamertag="Steve"))
    assert {p.xuid for p in tracker.snapshot().online_players} == {"100", "200"}

    tracker.on_event(PlayerDisconnected(raw="", xuid="100", gamertag="Alex"))
    assert {p.xuid for p in tracker.snapshot().online_players} == {"200"}

    await sup.stop()
    assert tracker.snapshot().online_players == ()


async def test_stop_for_any_reason_empties_online_list(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(crash_restart_threshold=0)
    tracker = StatusTracker(sup)
    import os

    os.environ["FAKE_BDS_CRASH_AFTER"] = "0.3"
    try:
        await sup.start()
        tracker.on_event(PlayerConnected(raw="", xuid="1", gamertag="A"))
        async with asyncio.timeout(5):
            await sup.wait_for_state(RunState.CRASHED)
    finally:
        os.environ.pop("FAKE_BDS_CRASH_AFTER", None)
    assert tracker.snapshot().online_players == ()


# -- 6.3 incomplete-observation flag ------------------------
async def test_incomplete_flag_set_when_attaching_to_running_server(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    tracker = StatusTracker(sup)
    await sup.start()
    tracker.mark_observation_incomplete()
    assert tracker.snapshot().players_incomplete is True
    await sup.stop()
    # cleared once the server is cleanly stopped (a fresh start re-observes)
    assert tracker.snapshot().players_incomplete is False


async def test_disconnect_for_unknown_player_marks_incomplete(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    tracker = StatusTracker(sup)
    await sup.start()
    tracker.on_event(PlayerDisconnected(raw="", xuid="999", gamertag="Ghost"))
    assert tracker.snapshot().players_incomplete is True
    await sup.stop()


async def test_spawn_without_connect_marks_incomplete(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    tracker = StatusTracker(sup)
    await sup.start()
    tracker.on_event(PlayerSpawned(raw="", xuid="777", gamertag="Late"))
    snap = tracker.snapshot()
    assert snap.players_incomplete is True
    assert {p.xuid for p in snap.online_players} == {"777"}
    await sup.stop()


# -- 6.4 push -------------------------------------------------
async def test_state_transition_and_crash_notify_connected_clients(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(crash_restart_threshold=0, readiness_timeout=5.0)
    tracker = StatusTracker(sup)

    updates: list[RunState] = []

    async def watch() -> None:
        async for snap in tracker.stream():
            updates.append(snap.run_state)
            if RunState.CRASHED in updates and RunState.RUNNING in updates:
                return

    task = asyncio.create_task(watch())
    await asyncio.sleep(0.05)

    import os

    os.environ["FAKE_BDS_CRASH_AFTER"] = "0.3"
    try:
        await sup.start()  # -> starting -> running (notifies)
        async with asyncio.timeout(5):
            await task  # crash notification arrives
    finally:
        os.environ.pop("FAKE_BDS_CRASH_AFTER", None)
        await sup.stop()

    assert RunState.RUNNING in updates
    assert RunState.CRASHED in updates
