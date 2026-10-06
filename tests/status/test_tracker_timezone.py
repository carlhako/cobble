"""maintenance-settings: next-run times identify their instant by carrying the
effective cobble timezone's UTC offset."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cobble.acquisition.layout import Layout
from cobble.backup.service import BackupService
from cobble.cobble_settings.service import CobbleSettingsService
from cobble.cobble_settings.store import CobbleSettingsStore
from cobble.status.tracker import StatusTracker
from cobble.supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio


class _FakeUpdate:
    available_version = None
    last_check_at = None
    last_result = None
    terminal = False

    def is_skipping(self, v) -> bool:
        return False


class _FakeScheduler:
    def __init__(self, *, backup_nxt=None, update_nxt=None) -> None:
        self._backup_nxt = backup_nxt
        self._update_nxt = update_nxt

    def backup_next_run(self):
        return self._backup_nxt

    def update_next_run(self):
        return self._update_nxt


def _tracker(make_supervisor, tmp_path, zone, **next_runs) -> StatusTracker:
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    czs = CobbleSettingsService(CobbleSettingsStore(tmp_path / "cobble_settings.json"))
    czs.set_timezone(zone)
    return StatusTracker(
        sup,
        backup=BackupService(sup._settings, layout, sup),
        update=_FakeUpdate(),
        scheduler=_FakeScheduler(**next_runs),
        cobble_settings=czs,
    )


async def test_next_runs_carry_the_effective_zones_offset(make_supervisor, tmp_path) -> None:
    t = _tracker(
        make_supervisor,
        tmp_path,
        "Australia/Brisbane",
        backup_nxt=datetime(2026, 10, 6, 18, 0, tzinfo=UTC),
        update_nxt=datetime(2026, 10, 6, 18, 0, tzinfo=UTC),
    )
    snap = t.snapshot()
    assert snap.backup.next_scheduled_at == "2026-10-07T04:00:00+10:00"
    assert snap.update.next_scheduled_at == "2026-10-07T04:00:00+10:00"


async def test_a_run_after_a_dst_change_carries_the_post_change_offset(
    make_supervisor, tmp_path
) -> None:
    # Sydney moves to +11:00 at 16:00Z on 3 October 2026; this run is after it.
    t = _tracker(
        make_supervisor,
        tmp_path,
        "Australia/Sydney",
        backup_nxt=datetime(2026, 10, 3, 17, 0, tzinfo=UTC),
    )
    assert t.snapshot().backup.next_scheduled_at == "2026-10-04T04:00:00+11:00"


async def test_no_next_run_is_reported_as_none(make_supervisor, tmp_path) -> None:
    t = _tracker(make_supervisor, tmp_path, "UTC")
    snap = t.snapshot()
    assert snap.backup.next_scheduled_at is None
    assert snap.update.next_scheduled_at is None
