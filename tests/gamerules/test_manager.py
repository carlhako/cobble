"""Sampling on readiness, the stopped-server view, and keeping the record
current with cobble's writes and live reads (tasks 3.3, 3.5, 3.6;
fix-gamerule-record-staleness)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

import cobble.gamerules.manager as manager_module
from cobble.events.model import ServerReady
from cobble.gamerules.manager import Classification, GameruleManager, Liveness
from cobble.gamerules.service import GameruleUnavailableError
from cobble.gamerules.storage import GameruleStorageError
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import MaintenanceInProgressError
from tests.gamerules.conftest import FIXED_NOW
from tests.gamerules.fakes import FakeGameruleService, FakeSupervisor, RaisingStore


# -- 3.3 sample and store on readiness ---------------------------
async def test_readiness_writes_a_record_for_the_active_world(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True, "pvp": False})
    await env.mgr.on_ready()
    rec = env.store.read_record("world-a")
    assert rec is not None
    assert rec.values == {"mobGriefing": True, "pvp": False}
    assert rec.sampled_at == FIXED_NOW.isoformat()  # the readiness time


async def test_on_ready_waits_for_the_running_transition_before_reconciling(
    make_manager,
) -> None:
    # The readiness event fires before the supervisor flips to RUNNING; on_ready
    # must wait for that so the first live read is not refused.
    env = make_manager(values={"pvp": True})
    env.sup.state = RunState.STARTING

    async def flip() -> RunState:
        env.sup.state = RunState.RUNNING
        return RunState.RUNNING

    env.sup.wait_for_state = lambda *_targets: flip()

    await env.mgr.on_ready()
    assert env.store.read_record("world-a") is not None


# -- 3.5 the current view -------------------------------------
async def test_view_is_live_when_running(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True})
    view = await env.mgr.current_view()
    assert view.liveness is Liveness.LIVE
    assert view.rules.get("mobGriefing").value is True
    assert view.level_name == "world-a"


async def test_view_is_recorded_when_stopped_with_a_record(make_manager) -> None:
    env = make_manager(values={"mobGriefing": False})
    await env.mgr.on_ready()  # lay down a record while "running"
    reads_before = env.svc.reads
    env.sup.set_running(False)

    view = await env.mgr.current_view()
    assert view.liveness is Liveness.RECORDED
    assert view.sampled_at == FIXED_NOW.isoformat()
    assert view.rules.get("mobGriefing").value is False
    assert env.svc.reads == reads_before  # no live read attempted while stopped


async def test_view_is_unread_for_a_never_run_world(make_manager) -> None:
    env = make_manager(running=False)
    view = await env.mgr.current_view()
    assert view.liveness is Liveness.UNREAD
    assert view.sampled_at is None
    assert len(view.rules) == 0  # nothing invented


async def test_view_falls_back_to_record_when_live_read_fails(make_manager) -> None:
    env = make_manager(values={"pvp": True})
    await env.mgr.on_ready()
    env.svc.unavailable = True  # running, but the read fails
    view = await env.mgr.current_view()
    assert view.liveness is Liveness.RECORDED
    assert view.rules.get("pvp").value is True


# -- 3.6 storage failures are logged and non-raising ---------
async def test_storage_failure_does_not_disrupt_readiness() -> None:
    sup = FakeSupervisor(running=True, level_name="world-a")
    svc = FakeGameruleService({"mobGriefing": True})
    mgr = GameruleManager(
        svc, RaisingStore(GameruleStorageError("disk gone")), sup, lambda: "world-a"
    )
    await mgr.on_ready()  # does not raise
    view = await mgr.current_view()
    # the live read still works; only the record/report lookups failed
    assert view.liveness is Liveness.LIVE
    assert view.report is None


# -- the record follows cobble's own writes (fix-gamerule-record-staleness) --
async def test_a_write_while_running_is_not_adopted_at_the_next_readiness(
    make_manager,
) -> None:
    env = make_manager(values={"keepInventory": False})
    await env.mgr.on_ready()  # baseline

    await env.mgr.write_rule("keepInventory", True)
    rec = env.store.read_record("world-a")
    assert rec.values["keepInventory"] is True

    outcome = await env.mgr.on_ready()  # restart / cobble upgrade
    assert outcome.classification is Classification.BASELINE
    assert env.store.read_report("world-a") is None


def _ready(env) -> asyncio.Task:
    """Deliver a readiness event; return the reconcile task it spawns."""
    env.mgr.on_event(ServerReady(raw="Server started."))
    (task,) = [t for t in asyncio.all_tasks() if t.get_name() == "cobble-gamerule-ready"]
    return task


async def _hold_readiness(env) -> tuple[asyncio.Task, asyncio.Event]:
    """Start a readiness reconcile and stall it before it takes the lock, as a
    server slow to reach RUNNING would, then report RUNNING. Set the returned
    event to let the reconcile go on."""
    gate = asyncio.Event()

    async def wait_for_state(*_targets):
        await gate.wait()
        return env.sup.state

    env.sup.wait_for_state = wait_for_state
    env.sup.state = RunState.STARTING
    ready = _ready(env)
    await asyncio.sleep(0)  # the reconcile task starts waiting on the gate
    env.sup.set_running(True)
    return ready, gate


async def test_a_live_read_does_not_adopt_until_this_runs_readiness_has_decided(
    make_manager,
) -> None:
    env = make_manager(values={"pvp": True})
    await env.mgr.on_ready()  # a previous run

    env.svc.values["pvp"] = False  # changed in game while cobble was down
    ready = _ready(env)  # the next start: nothing awaited, the reconcile has not run yet
    await env.mgr.current_view()
    assert env.store.read_report("world-a") is None

    outcome = await ready
    assert outcome.classification is Classification.ADOPTION
    assert outcome.rules == {"pvp": False}


async def test_a_write_racing_readiness_still_gets_first_sight_defaults(
    make_manager,
) -> None:
    env = make_manager(values={"keepInventory": False, "pvp": True})
    env.store.set_default("keepInventory", True)

    ready = _ready(env)
    await env.mgr.write_rule("pvp", False)  # lands before the reconcile task runs
    outcome = await ready

    assert outcome.classification is Classification.DEFAULTS
    assert env.store.read_report("world-a").kind == "defaults"
    assert env.store.read_record("world-a").values == {"keepInventory": True, "pvp": False}


# -- a live read adopts an outside change (design.md D3) -------
async def test_a_live_read_adopts_an_outside_change_and_returns_the_report(
    make_manager,
) -> None:
    env = make_manager(values={"mobGriefing": True, "pvp": True})
    await env.mgr.on_ready()

    env.svc.values["mobGriefing"] = False  # changed in game
    view = await env.mgr.current_view()

    assert view.report is not None
    assert view.report.kind == "adoption"
    assert view.report.rules == {"mobGriefing": False}
    assert env.store.read_record("world-a").values["mobGriefing"] is False


async def test_a_matching_live_read_leaves_the_record_alone_and_reports_nothing(
    make_manager,
) -> None:
    # Rewriting an unchanged record would only move last_read_at in the status
    # payload, which makes every open Gamerules section reload.
    now = [datetime(2026, 4, 1, 9, 0, tzinfo=UTC)]
    env = make_manager(values={"pvp": True}, clock=lambda: now[0])
    await env.mgr.on_ready()
    now[0] = datetime(2026, 4, 1, 9, 5, tzinfo=UTC)

    view = await env.mgr.current_view()
    assert view.report is None
    rec = env.store.read_record("world-a")
    assert rec.values == {"pvp": True}
    assert rec.sampled_at == datetime(2026, 4, 1, 9, 0, tzinfo=UTC).isoformat()


async def test_consecutive_live_read_adoptions_accumulate_in_one_report(
    make_manager,
) -> None:
    env = make_manager(values={"mobGriefing": True, "pvp": True})
    await env.mgr.on_ready()

    env.svc.values["mobGriefing"] = False
    await env.mgr.current_view()
    env.svc.values["pvp"] = False
    view = await env.mgr.current_view()

    # the first change is still reported although the record already holds it
    assert view.report.kind == "adoption"
    assert view.report.rules == {"mobGriefing": False, "pvp": False}


async def test_an_adoption_after_acknowledgement_starts_a_fresh_report(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True, "pvp": True})
    await env.mgr.on_ready()
    env.svc.values["mobGriefing"] = False
    await env.mgr.current_view()
    env.mgr.acknowledge_report("world-a")

    env.svc.values["pvp"] = False
    view = await env.mgr.current_view()
    assert view.report.rules == {"pvp": False}


async def test_a_change_adopted_at_a_live_read_is_not_reported_again_at_readiness(
    make_manager,
) -> None:
    env = make_manager(values={"mobGriefing": True})
    await env.mgr.on_ready()
    env.svc.values["mobGriefing"] = False
    await env.mgr.current_view()  # adopted and reported here
    env.mgr.acknowledge_report("world-a")

    outcome = await env.mgr.on_ready()
    assert outcome.classification is Classification.BASELINE
    assert env.store.read_report("world-a") is None


async def test_a_live_read_before_readiness_touches_nothing_and_restore_still_repairs(
    make_manager,
) -> None:
    env = make_manager(values={"mobGriefing": True})
    await env.mgr.on_ready()  # a previous run: record says mobGriefing=true

    # a restore brings back a world whose live value differs
    env.svc.values["mobGriefing"] = False
    env.store.set_restore_marker("world-a", FIXED_NOW)
    record_before = env.store.read_record("world-a")

    ready = _ready(env)
    view = await env.mgr.current_view()  # a page load racing the reconcile
    assert view.liveness is Liveness.LIVE
    assert view.report is None
    assert env.store.read_record("world-a") == record_before
    assert env.store.restore_marker() == "world-a"

    outcome = await ready
    assert outcome.classification is Classification.REPAIR
    assert env.svc.values["mobGriefing"] is True


async def test_a_live_read_during_a_write_does_not_adopt_the_write(make_manager) -> None:
    env = make_manager(values={"keepInventory": False})
    await env.mgr.on_ready()

    sent = asyncio.Event()
    release = asyncio.Event()
    real_write = env.svc.write

    async def slow_write(name, value):
        result = await real_write(name, value)  # the server now has the new value
        sent.set()
        await release.wait()  # ...but the re-read has not come back yet
        return result

    env.svc.write = slow_write
    write = asyncio.create_task(env.mgr.write_rule("keepInventory", True))
    await sent.wait()
    read = asyncio.create_task(env.mgr.current_view())
    await asyncio.sleep(0)
    release.set()
    await write
    view = await read

    assert view.report is None
    assert env.store.read_report("world-a") is None
    assert env.store.read_record("world-a").values["keepInventory"] is True


async def test_a_live_read_before_readiness_does_not_wait_for_the_reconcile(
    make_manager,
) -> None:
    env = make_manager(values={"pvp": True})
    await env.mgr.on_ready()

    # the readiness reconcile takes the lock, then its read hangs
    gate = asyncio.Event()
    real_read = env.svc.read_live
    first = [True]

    async def read_live():
        if first[0]:
            first[0] = False
            await gate.wait()
        return await real_read()

    env.svc.read_live = read_live
    ready = _ready(env)
    await asyncio.sleep(0)  # the reconcile task starts and blocks inside the lock

    view = await asyncio.wait_for(env.mgr.current_view(), 1.0)
    assert view.liveness is Liveness.LIVE
    gate.set()
    await ready


# -- a write's re-read also reveals in-game changes -------------
async def test_a_write_adopts_an_in_game_change_to_another_rule(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True, "pvp": True})
    await env.mgr.on_ready()

    env.svc.values["mobGriefing"] = False  # changed in game; no page load since
    await env.mgr.write_rule("pvp", False)

    report = env.store.read_report("world-a")
    assert report is not None and report.kind == "adoption"
    assert report.rules == {"mobGriefing": False}  # cobble's own pvp write is not in it
    assert env.store.read_record("world-a").values == {"mobGriefing": False, "pvp": False}


async def test_a_write_whose_reread_is_lost_is_still_recorded(make_manager) -> None:
    env = make_manager(values={"keepInventory": False, "pvp": True})
    await env.mgr.on_ready()

    env.svc.lose_reread = True
    with pytest.raises(GameruleUnavailableError):
        await env.mgr.write_rule("keepInventory", True)
    assert env.store.read_record("world-a").values == {"keepInventory": True, "pvp": True}

    env.svc.lose_reread = False
    view = await env.mgr.current_view()
    assert view.report is None


# -- the readiness wait before a write (design.md D2) ------------
async def test_a_write_goes_ahead_when_readiness_does_not_finish_in_time(
    make_manager, monkeypatch
) -> None:
    monkeypatch.setattr(manager_module, "_READINESS_WAIT", 0.01)
    env = make_manager(values={"keepInventory": False})
    await env.mgr.on_ready()
    ready, gate = await _hold_readiness(env)

    result = await env.mgr.write_rule("keepInventory", True)
    assert result.queued is False
    assert env.store.read_record("world-a").values == {"keepInventory": True}

    gate.set()
    outcome = await ready
    assert outcome.classification is Classification.BASELINE
    assert env.store.read_report("world-a") is None


async def test_a_write_is_refused_when_maintenance_begins_during_the_wait(
    make_manager,
) -> None:
    env = make_manager(values={"keepInventory": False})
    await env.mgr.on_ready()
    ready, gate = await _hold_readiness(env)

    write = asyncio.create_task(env.mgr.write_rule("keepInventory", True))
    await asyncio.sleep(0)
    env.sup.maintenance = "backup"
    gate.set()
    with pytest.raises(MaintenanceInProgressError):
        await write
    assert env.svc.writes == []
    await ready


async def test_a_write_is_queued_when_the_server_stops_during_the_wait(
    make_manager,
) -> None:
    env = make_manager(values={"keepInventory": False})
    await env.mgr.on_ready()
    ready, gate = await _hold_readiness(env)

    write = asyncio.create_task(env.mgr.write_rule("keepInventory", True))
    await asyncio.sleep(0)
    env.sup.set_running(False)
    gate.set()
    result = await write
    assert result.queued is True
    assert env.svc.writes == []
    assert env.store.read_pending("world-a") == {"keepInventory": True}
    await ready


# -- a repair the server partly refuses (design.md D6) -----------
async def test_a_refused_repair_value_is_not_reported_as_an_in_game_change(
    make_manager,
) -> None:
    env = make_manager(values={"mobGriefing": True, "pvp": True})
    await env.mgr.on_ready()  # record: both true

    env.svc.values.update(mobGriefing=False, pvp=False)  # the restored world
    env.store.set_restore_marker("world-a", FIXED_NOW)
    env.svc.refuse["pvp"] = "refused by this server version"

    outcome = await env.mgr.on_ready()
    assert outcome.classification is Classification.REPAIR
    assert env.store.read_report("world-a").rules == {"mobGriefing": True}

    view = await env.mgr.current_view()
    assert view.report.kind == "repair"
