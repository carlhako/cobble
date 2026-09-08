"""Sampling on readiness / pre-stop and the stopped-server view
(tasks 3.3, 3.4, 3.5, 3.6)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from cobble.gamerules.manager import GameruleManager, Liveness
from cobble.gamerules.storage import GameruleStorageError
from cobble.supervisor.state import RunState
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


# -- 3.4 opportunistic pre-stop sample, best-effort ------------
async def test_pre_stop_stores_a_completed_sample(make_manager) -> None:
    env = make_manager(values={"keepInventory": True})
    when = datetime(2026, 4, 1, 10, 30, 0, tzinfo=UTC)
    env.sup.fire_pre_stop(when)
    await asyncio.sleep(0.02)  # let the fire-and-forget task run
    rec = env.store.read_record("world-a")
    assert rec.values == {"keepInventory": True}
    assert rec.sampled_at == when.isoformat()


async def test_failing_pre_stop_sample_leaves_the_prior_record_intact(make_manager) -> None:
    env = make_manager(values={"keepInventory": True})
    await env.mgr.on_ready()
    prior = env.store.read_record("world-a")

    env.svc.unavailable = True  # the server won't answer during shutdown
    env.sup.fire_pre_stop(datetime(2026, 4, 1, 11, 0, 0, tzinfo=UTC))
    await asyncio.sleep(0.02)

    after = env.store.read_record("world-a")
    assert after.values == prior.values
    assert after.sampled_at == prior.sampled_at  # timestamp unchanged


async def test_sample_and_store_returns_false_when_unavailable(make_manager) -> None:
    env = make_manager()
    env.svc.unavailable = True
    assert await env.mgr.sample_and_store(reason="readiness") is False
    assert env.store.read_record("world-a") is None


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
    assert await mgr.sample_and_store(reason="readiness") is False
    view = await mgr.current_view()
    # the live read still works; only the record/report lookups failed
    assert view.liveness is Liveness.LIVE
    assert view.report is None
