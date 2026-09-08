"""Section 9: version / update / backup / maintenance fields in status.

Tasks 9.1-9.4 (and the push half of 8.3).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from cobble.acquisition.layout import Layout
from cobble.backup.service import BackupService
from cobble.status.tracker import StatusTracker
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio


class _FakeUpdate:
    def __init__(self) -> None:
        self.available_version = None
        self.last_check_at = None
        self.last_result = None
        self.terminal = False
        self._skip: set[str] = set()

    def is_skipping(self, v):
        return v in self._skip


class _FakeScheduler:
    def __init__(self, nxt=None):
        self._nxt = nxt

    def next_run(self):
        return self._nxt


# -- 9.1 installed + available, unknown before any check ------------
async def test_available_version_unknown_before_any_check(make_supervisor) -> None:
    sup: Supervisor = make_supervisor("1.0.0.1")
    fu = _FakeUpdate()
    t = StatusTracker(sup, update=fu, scheduler=_FakeScheduler())
    v = t.snapshot().version_info
    assert v.installed == "1.0.0.1"
    assert v.available is None and v.up_to_date is None  # unknown, no error


async def test_available_version_reported_after_a_check(make_supervisor) -> None:
    sup: Supervisor = make_supervisor("1.0.0.1")
    fu = _FakeUpdate()
    fu.available_version = "2.0.0.1"
    t = StatusTracker(sup, update=fu, scheduler=_FakeScheduler())
    v = t.snapshot().version_info
    assert v.available == "2.0.0.1" and v.up_to_date is False

    fu.available_version = "1.0.0.1"
    assert t.snapshot().version_info.up_to_date is True


# -- 9.2 update activity ------------------------------------
async def test_update_fields_after_success_failure_and_skip(make_supervisor) -> None:
    sup: Supervisor = make_supervisor("1.0.0.1")
    fu = _FakeUpdate()
    from datetime import datetime

    sched = _FakeScheduler(datetime(2026, 6, 2, 4, 0))
    t = StatusTracker(sup, update=fu, scheduler=sched)

    fu.last_check_at = "2026-06-01T04:00:00"
    fu.last_result = SimpleNamespace(
        status="success",
        at="2026-06-01T04:05:00",
        detail="ok",
        from_version="1.0.0.1",
        to_version="2.0.0.1",
        step=None,
    )
    u = t.snapshot().update
    assert u.last_check_at == "2026-06-01T04:00:00"
    assert u.last_result["status"] == "success"
    assert u.next_scheduled_at == "2026-06-02T04:00:00"

    fu.available_version = "2.0.0.1"
    fu._skip.add("2.0.0.1")
    assert t.snapshot().update.skipping == "2.0.0.1"

    fu.terminal = True
    assert t.snapshot().update.terminal is True


# -- 9.3 backup activity -----------------------------------
async def test_backup_unhealthy_condition_appears_and_clears(make_supervisor) -> None:
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    bs = BackupService(sup._settings, layout, sup)
    t = StatusTracker(sup, backup=bs, scheduler=_FakeScheduler())

    assert t.snapshot().backup.unhealthy is None
    bs._health = "backup destination is not writable"
    assert t.snapshot().backup.unhealthy == "backup destination is not writable"

    (layout.data_dir / "server.properties").write_text("x\n")
    await bs.capture(reason="manual")  # a success clears health
    b = t.snapshot().backup
    assert b.unhealthy is None
    assert b.last_ok is True and b.count == 1


# -- 9.4 maintenance distinct from run state ---------------
async def test_maintenance_is_reported_alongside_the_run_state(make_supervisor) -> None:
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    t = StatusTracker(sup)

    await sup.start()
    async with sup.maintenance_scope("updating") as h:
        h.set_step("activating 2.0.0.1")
        snap = t.snapshot()
        assert snap.run_state is RunState.RUNNING  # still describes the process
        assert snap.maintenance is not None
        assert snap.maintenance.operation == "updating"
        assert snap.maintenance.step == "activating 2.0.0.1"
    assert t.snapshot().maintenance is None
    await sup.stop()


async def test_maintenance_step_changes_are_pushed_without_polling(make_supervisor) -> None:
    # 8.3 push half: a connected stream client is notified on a maintenance step.
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    t = StatusTracker(sup)
    seen: list = []

    async def consume():
        async for snap in t.stream():
            seen.append(snap.maintenance)
            if len(seen) >= 3:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    async with sup.maintenance_scope("backing_up") as h:
        await asyncio.sleep(0.02)
        h.set_step("capturing")
        await asyncio.sleep(0.02)
    await asyncio.wait_for(task, timeout=2)
    ops = [m.operation if m else None for m in seen]
    assert "backing_up" in ops
    steps = [m.step for m in seen if m]
    assert "capturing" in steps
