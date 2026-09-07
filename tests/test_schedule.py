"""Section 7: the in-process nightly maintenance scheduler (tasks 7.1-7.4)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from cobble.schedule import Scheduler, parse_hhmm
from cobble.settings import Settings
from cobble.update.service import UpdateCheck

pytestmark = pytest.mark.asyncio


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


class _StubUpdate:
    def __init__(self, check: UpdateCheck) -> None:
        self._check = check
        self.checks = 0
        self.applied: list[str] = []

    async def check(self) -> UpdateCheck:
        self.checks += 1
        return self._check

    async def apply(self, *, reason: str):
        self.applied.append(reason)
        return SimpleNamespace(status="success")


class _StubBackup:
    def __init__(self) -> None:
        self.captured: list[str] = []

    async def capture(self, *, reason: str) -> None:
        self.captured.append(reason)


def _check(*, available=None, up_to_date=False, skipped=False, error=None) -> UpdateCheck:
    return UpdateCheck(
        installed="1.0.0.1",
        available=available,
        up_to_date=up_to_date,
        skipped=skipped,
        skipped_reason="quarantined" if skipped else None,
        error=error,
    )


def _settings(tmp_path, **over) -> Settings:
    base = dict(
        bedrock_root=tmp_path / "b",
        state_dir=tmp_path / "s",
        backup_dir=tmp_path / "k",
        maintenance_time="04:00",
        bootstrap_on_start=False,
    )
    base.update(over)
    s = Settings(**base)
    for d in (s.bedrock_root, s.state_dir, s.backup_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s


# -- 7.1 schedule maths --------------------------------------------
async def test_parse_hhmm() -> None:
    assert parse_hhmm("04:00") == (4, 0)
    assert parse_hhmm("23:59") == (23, 59)
    assert parse_hhmm("") is None
    assert parse_hhmm("24:00") is None
    assert parse_hhmm("nope") is None


async def test_next_run_is_todays_or_tomorrows_local_time(tmp_path) -> None:
    clock = _Clock(datetime(2026, 6, 1, 3, 30))  # before 04:00
    sch = Scheduler(_settings(tmp_path), _StubBackup(), _StubUpdate(_check()), clock=clock)
    assert sch.next_run() == datetime(2026, 6, 1, 4, 0)

    clock.now = datetime(2026, 6, 1, 4, 30)  # after 04:00
    assert sch.next_run() == datetime(2026, 6, 2, 4, 0)


async def test_next_run_tracks_wall_clock_across_a_dst_jump(tmp_path) -> None:
    # The next run is always the next 04:00 on the wall clock, recomputed from
    # local time each call — so a DST shift of the underlying clock does not
    # drift it. (2026-03-08 is the US spring-forward date.)
    clock = _Clock(datetime(2026, 3, 7, 23, 0))
    sch = Scheduler(_settings(tmp_path), _StubBackup(), _StubUpdate(_check()), clock=clock)
    assert sch.next_run() == datetime(2026, 3, 8, 4, 0)
    # clock advances past 02:00->03:00 spring-forward; still points at 04:00
    clock.now = datetime(2026, 3, 8, 3, 15)
    assert sch.next_run() == datetime(2026, 3, 8, 4, 0)


async def test_disabled_schedule_reports_no_next_run(tmp_path) -> None:
    sch = Scheduler(
        _settings(tmp_path, maintenance_time=""), _StubBackup(), _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 1, 3, 0)),
    )
    assert sch.next_run() is None
    sch2 = Scheduler(
        _settings(tmp_path, backup_enabled=False, update_enabled=False),
        _StubBackup(), _StubUpdate(_check()), clock=_Clock(datetime(2026, 6, 1, 3, 0)),
    )
    assert sch2.next_run() is None


# -- 7.2 single ordered window ------------------------------------
async def test_window_with_an_available_update_does_not_also_run_a_standalone_backup(
    tmp_path,
) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1"))
    sch = Scheduler(_settings(tmp_path), backup, update, clock=_Clock(datetime(2026, 6, 1, 4, 1)))
    await sch.run_now()
    assert update.applied == ["scheduled"]  # the update ran
    assert backup.captured == []  # its pre-update backup covered the nightly backup


async def test_window_without_an_update_runs_a_standalone_backup(tmp_path) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(up_to_date=True))
    sch = Scheduler(_settings(tmp_path), backup, update, clock=_Clock(datetime(2026, 6, 1, 4, 1)))
    await sch.run_now()
    assert update.applied == []
    assert backup.captured == ["scheduled"]


async def test_window_skips_the_update_for_a_quarantined_version_but_still_backs_up(
    tmp_path,
) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1", skipped=True))
    sch = Scheduler(_settings(tmp_path), backup, update, clock=_Clock(datetime(2026, 6, 1, 4, 1)))
    await sch.run_now()
    assert update.applied == []
    assert backup.captured == ["scheduled"]


async def test_backup_only_schedule_never_checks_for_updates(tmp_path) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1"))
    sch = Scheduler(
        _settings(tmp_path, update_enabled=False), backup, update,
        clock=_Clock(datetime(2026, 6, 1, 4, 1)),
    )
    await sch.run_now()
    assert update.checks == 0
    assert backup.captured == ["scheduled"]


# -- 7.1 missed window ---------------------------------------
async def test_missed_window_runs_once_shortly_after_start(tmp_path) -> None:
    # cobble comes up at 05:00, after the 04:00 window it was down for.
    clock = _Clock(datetime(2026, 6, 1, 5, 0))
    backup, update = _StubBackup(), _StubUpdate(_check(up_to_date=True))
    sch = Scheduler(_settings(tmp_path), backup, update, clock=clock)
    sch._load_marker()
    assert sch._missed_window(clock()) is True
    await sch._run_window(reason="catch-up")
    assert backup.captured == ["scheduled"]
    # marker recorded -> not considered missed again today
    assert sch._missed_window(clock()) is False


async def test_window_already_run_today_is_not_a_missed_window(tmp_path) -> None:
    s = _settings(tmp_path)
    clock = _Clock(datetime(2026, 6, 1, 5, 0))
    sch = Scheduler(s, _StubBackup(), _StubUpdate(_check(up_to_date=True)), clock=clock)
    sch._record_window(clock())
    # a fresh scheduler over the same state dir (a restart) reads the marker
    sch2 = Scheduler(s, _StubBackup(), _StubUpdate(_check(up_to_date=True)), clock=clock)
    sch2._load_marker()
    assert sch2._missed_window(clock()) is False


# -- 7.4 on-demand reuses the sequence -----------------------
async def test_run_now_uses_the_same_sequence_regardless_of_time(tmp_path) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1"))
    # 14:00 — nowhere near the scheduled window
    sch = Scheduler(_settings(tmp_path), backup, update, clock=_Clock(datetime(2026, 6, 1, 14, 0)))
    await sch.run_now()
    assert update.applied == ["scheduled"]
