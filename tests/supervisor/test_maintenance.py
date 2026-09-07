"""Section 2: maintenance state and lifecycle interlock (tasks 2.1-2.6)."""

from __future__ import annotations

import asyncio
import os

import pytest

from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import (
    MaintenanceConflictError,
    MaintenanceInProgressError,
    Supervisor,
    TransitionInProgressError,
)

pytestmark = pytest.mark.asyncio


async def _wait_state(sup: Supervisor, target: RunState) -> None:
    async with asyncio.timeout(15):
        await sup.wait_for_state(target)


async def test_maintenance_absent_when_idle_and_observable_while_running(make_supervisor) -> None:
    # 2.1 the maintenance value is absent when idle, set while an operation runs,
    # and reported through a listener independently of the run state.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    seen: list[tuple[str | None, str | None]] = []
    sup.subscribe_maintenance(lambda op, step: seen.append((op, step)))

    assert sup.maintenance is None
    await sup.start()

    async with sup.maintenance_scope("updating") as handle:
        assert sup.maintenance == "updating"
        assert sup.state is RunState.RUNNING  # run state still describes the process
        handle.set_step("downloading")
        assert sup.maintenance_step == "downloading"

    assert sup.maintenance is None
    assert sup.maintenance_step is None
    assert ("updating", None) in seen
    assert ("updating", "downloading") in seen
    assert seen[-1] == (None, None)  # ended
    await sup.stop()


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
async def test_lifecycle_actions_rejected_during_maintenance(make_supervisor, action) -> None:
    # 2.2 start/stop/restart are rejected while maintenance is in progress, with
    # an error distinguishable from the existing transition errors.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    async with sup.maintenance_scope("restoring"):
        with pytest.raises(MaintenanceInProgressError) as ei:
            await getattr(sup, action)()
    assert ei.value.code == "maintenance_in_progress"
    assert ei.value.code != TransitionInProgressError.code
    assert "restoring" in str(ei.value)
    await sup.stop()


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
async def test_lifecycle_rejection_is_immediate_even_while_a_step_holds_the_lock(
    make_supervisor, action
) -> None:
    # A maintenance step (e.g. awaiting readiness of a new version) can hold
    # `_op_lock` for the readiness timeout. An operator's Stop/Restart must be
    # rejected at once, not queue behind that wait.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    async with sup.maintenance_scope("updating"):
        async with sup._op_lock:  # simulate a step holding the lock
            with pytest.raises(MaintenanceInProgressError):
                await asyncio.wait_for(getattr(sup, action)(), timeout=0.5)
    await sup.stop()


async def test_maintenance_refused_during_a_lifecycle_transition(make_supervisor) -> None:
    # 2.3 a maintenance operation cannot begin while a transition is in flight;
    # the request fails and no maintenance state is set.
    sup: Supervisor = make_supervisor(shutdown_timeout=2.0)
    os.environ["FAKE_BDS_IGNORE_STOP"] = "1"
    try:
        await sup.start()
        stopping = asyncio.create_task(sup.stop())
        await asyncio.sleep(0.1)  # let stop() take _op_lock and enter STOPPING
        assert sup.state is RunState.STOPPING
        with pytest.raises(TransitionInProgressError):
            async with sup.maintenance_scope("updating"):
                pass
        assert sup.maintenance is None
        await stopping
    finally:
        os.environ.pop("FAKE_BDS_IGNORE_STOP", None)


async def test_maintenance_conflict_when_one_already_in_progress(make_supervisor) -> None:
    # 6.14 (interlock half) a second maintenance operation is rejected with a
    # distinguishable error.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    async with sup.maintenance_scope("updating"):
        with pytest.raises(MaintenanceConflictError) as ei:
            async with sup.maintenance_scope("restoring"):
                pass
        assert ei.value.code == "maintenance_conflict"
    await sup.stop()


async def test_crash_during_maintenance_is_not_auto_restarted_and_is_observed(
    make_supervisor,
) -> None:
    # 2.4 a server that exits during maintenance is not auto-restarted; the
    # maintenance operation observes the exit.
    sup: Supervisor = make_supervisor(
        crash_restart_threshold=3, crash_restart_window=60.0, readiness_timeout=3.0
    )
    await sup.start()
    async with sup.maintenance_scope("updating") as handle:
        # Kill the process out from under the maintenance operation.
        sup._proc.kill()  # type: ignore[union-attr]
        exit_info = await asyncio.wait_for(handle.wait_exit(), timeout=10)
        assert exit_info.crashed is True
        await asyncio.sleep(0.5)
        assert sup.state is RunState.CRASHED  # NOT restarted
    # 2.5 normal crash-restart behaviour is restored after maintenance ends.
    assert sup._auto_restart_enabled is True
    await sup.start()
    assert sup.state is RunState.RUNNING
    await sup.stop()


async def test_crash_after_maintenance_is_auto_restarted_again(make_supervisor) -> None:
    # 2.5 a crash after maintenance completes is auto-restarted as before.
    sup: Supervisor = make_supervisor(
        crash_restart_threshold=3, crash_restart_window=60.0, readiness_timeout=3.0
    )
    await sup.start()
    async with sup.maintenance_scope("updating"):
        pass

    os.environ["FAKE_BDS_CRASH_AFTER"] = "0.2"
    await sup.restart()
    await asyncio.sleep(0.5)
    os.environ.pop("FAKE_BDS_CRASH_AFTER", None)
    await _wait_state(sup, RunState.RUNNING)
    assert sup.state is RunState.RUNNING
    await sup.stop()


async def test_cobble_termination_during_maintenance_stops_cleanly(make_supervisor) -> None:
    # 2.6 a termination signal mid-operation stops the server cleanly; the
    # operation must not be able to claim success afterwards.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()

    completed_normally = False
    async with sup.maintenance_scope("updating"):
        await sup.aclose()  # cobble is going down
        assert sup.state is RunState.STOPPED
        assert sup.last_shutdown is not None and sup.last_shutdown.clean is True
        # A start attempted by the operation after this point must fail.
        with pytest.raises(TransitionInProgressError):
            await sup.maintenance_start()
        completed_normally = True
    assert completed_normally  # the CM still unwinds cleanly
    assert sup.maintenance is None
