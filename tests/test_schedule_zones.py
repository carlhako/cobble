"""Zone-aware scheduling (maintenance-settings spec: schedules run in the cobble
timezone; daylight-saving transitions neither skip nor repeat a run)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import cobble.schedule as schedule_mod
from cobble.cobble_settings.service import CobbleSettingsService
from cobble.cobble_settings.store import CobbleSettingsStore
from cobble.maintenance.schedule_config import ScheduleConfig
from cobble.maintenance.service import MaintenanceSettingsService
from cobble.maintenance.settings_store import MaintenanceSettingsStore
from cobble.schedule import Scheduler, _next_after
from cobble.settings import Settings

BRISBANE = ZoneInfo("Australia/Brisbane")
SYDNEY = ZoneInfo("Australia/Sydney")


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _daily(time: str) -> ScheduleConfig:
    return ScheduleConfig(enabled=True, time=time, frequency="daily", day=None)


# -- 2.2 cross-zone -------------------------------------------------
def test_daily_in_brisbane_on_a_utc_host_runs_the_previous_utc_day() -> None:
    nxt = _next_after(_daily("04:00"), _utc(2026, 10, 6, 12, 0), BRISBANE)
    assert nxt == _utc(2026, 10, 6, 18, 0)
    assert nxt.astimezone(BRISBANE).isoformat() == "2026-10-07T04:00:00+10:00"


def test_daily_runs_today_when_the_zones_clock_has_not_reached_it() -> None:
    # 17:00Z is 03:00 Brisbane on the 7th, so 04:00 is an hour away.
    assert _next_after(_daily("04:00"), _utc(2026, 10, 6, 17, 0), BRISBANE) == _utc(
        2026, 10, 6, 18, 0
    )


def test_weekly_monday_in_brisbane_fires_on_sunday_in_utc() -> None:
    cfg = ScheduleConfig(enabled=True, time="04:00", frequency="weekly", day=0)
    nxt = _next_after(cfg, _utc(2026, 10, 1, 0, 0), BRISBANE)  # a Thursday
    assert nxt == _utc(2026, 10, 4, 18, 0)
    assert nxt.weekday() == 6  # Sunday in UTC
    assert nxt.astimezone(BRISBANE).weekday() == 0  # Monday in Brisbane


def test_monthly_day_31_still_clamps_in_the_zone() -> None:
    cfg = ScheduleConfig(enabled=True, time="04:00", frequency="monthly", day=31)
    assert _next_after(cfg, _utc(2026, 4, 1, 0, 0), BRISBANE) == _utc(2026, 4, 29, 18, 0)
    # 20:00Z on 29 April is already 06:00 on the 30th in Brisbane: April is done.
    assert _next_after(cfg, _utc(2026, 4, 29, 20, 0), BRISBANE) == _utc(2026, 5, 30, 18, 0)


def test_monthly_rolls_the_year_in_the_zone() -> None:
    cfg = ScheduleConfig(enabled=True, time="04:00", frequency="monthly", day=1)
    # 15:00Z on 31 December is 01:00 on 1 January in Brisbane, so 04:00 is still ahead.
    assert _next_after(cfg, _utc(2026, 12, 31, 15, 0), BRISBANE) == _utc(2026, 12, 31, 18, 0)
    # By 19:00Z that has passed, and the next first of the month is in February.
    assert _next_after(cfg, _utc(2026, 12, 31, 19, 0), BRISBANE) == _utc(2027, 1, 31, 18, 0)


# -- 2.3 DST --------------------------------------------------------
def test_spring_forward_gap_time_runs_once_at_the_shifted_time() -> None:
    cfg = _daily("02:30")
    # Sydney: 2026-10-04 02:00+10:00 -> 03:00+11:00, so 02:30 does not exist.
    first = _next_after(cfg, _utc(2026, 10, 2, 12, 0), SYDNEY)
    assert first == _utc(2026, 10, 2, 16, 30)  # 02:30+10:00 on the 3rd
    gap_day = _next_after(cfg, first, SYDNEY)
    assert gap_day == _utc(2026, 10, 3, 16, 30)
    assert gap_day.astimezone(SYDNEY).isoformat() == "2026-10-04T03:30:00+11:00"
    following = _next_after(cfg, gap_day, SYDNEY)
    assert following.astimezone(SYDNEY).isoformat() == "2026-10-05T02:30:00+11:00"


def test_fall_back_repeated_time_runs_at_its_first_occurrence_only() -> None:
    cfg = _daily("02:30")
    # Sydney: 2026-04-05 03:00+11:00 -> 02:00+10:00, so 02:30 happens twice.
    nxt = _next_after(cfg, _utc(2026, 4, 3, 12, 0), SYDNEY)
    assert nxt == _utc(2026, 4, 3, 15, 30)  # 02:30+11:00 on the 4th
    transition_day = _next_after(cfg, nxt, SYDNEY)
    assert transition_day == _utc(2026, 4, 4, 15, 30)
    assert transition_day.astimezone(SYDNEY).isoformat() == "2026-04-05T02:30:00+11:00"
    # Asked again from the second 02:30 (fold=1, 16:30Z), the next run is the
    # following day's, never the repeat.
    second_02_30 = _utc(2026, 4, 4, 16, 30)
    assert second_02_30.astimezone(SYDNEY).fold == 1
    assert _next_after(cfg, second_02_30, SYDNEY) == _utc(2026, 4, 5, 16, 30)
    assert _next_after(cfg, transition_day, SYDNEY) == _utc(2026, 4, 5, 16, 30)


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        (_utc(2026, 10, 3, 0, 0), _utc(2026, 10, 3, 17, 0)),  # 04:00+11:00 on the 4th
        (_utc(2026, 4, 4, 0, 0), _utc(2026, 4, 4, 18, 0)),  # 04:00+10:00 on the 5th
    ],
)
def test_a_04_00_schedule_on_a_transition_day_runs_at_04_00_local(after, expected) -> None:
    nxt = _next_after(_daily("04:00"), after, SYDNEY)
    assert nxt == expected
    assert (nxt.hour, nxt.minute) != (4, 0)  # it is 04:00 *local*, not UTC
    assert nxt.astimezone(SYDNEY).strftime("%H:%M") == "04:00"


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def _scheduler(tmp_path, clock, *, zone: str, time: str) -> Scheduler:
    settings = Settings(
        bedrock_root=tmp_path / "b",
        state_dir=tmp_path / "s",
        backup_dir=tmp_path / "k",
        maintenance_time="04:00",
        bootstrap_on_start=False,
    )
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    store = MaintenanceSettingsStore(settings.state_dir / "maintenance_settings.json")
    store.set(
        backup_schedule=_daily(time), update_schedule=ScheduleConfig(False, time, "daily", None)
    )
    czs = CobbleSettingsService(CobbleSettingsStore(settings.state_dir / "cobble_settings.json"))
    czs.set_timezone(zone)
    return Scheduler(
        settings,
        SimpleNamespace(),
        SimpleNamespace(),
        supervisor=SimpleNamespace(),
        maintenance_settings=MaintenanceSettingsService(store, settings),
        cobble_settings=czs,
        clock=clock,
    )


async def _drive(sch: Scheduler, clock: _Clock, *, until: datetime, monkeypatch, max_sleep=None):
    """Run the real loop against a fake clock: every sleep advances the clock by
    exactly the requested time. Returns (runs, delays, wakes)."""
    runs: list[datetime] = []
    delays: list[float] = []
    wakes: list[datetime] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)
        wakes.append(clock.now)
        if clock.now >= until or len(delays) > 5000:
            raise asyncio.CancelledError
        clock.now += timedelta(seconds=max(0.0, seconds))

    async def fake_window(*, reason, want_backup, want_update) -> None:
        runs.append(clock.now)

    monkeypatch.setattr(sch, "_sleep_until", fake_sleep)
    monkeypatch.setattr(sch, "_run_window", fake_window)
    if max_sleep is not None:
        monkeypatch.setattr(schedule_mod, "_MAX_SLEEP", max_sleep)
    with pytest.raises(asyncio.CancelledError):
        await sch._loop()
    return runs, delays, wakes


@pytest.mark.asyncio
async def test_loop_runs_once_through_the_spring_forward_gap(tmp_path, monkeypatch) -> None:
    clock = _Clock(_utc(2026, 10, 2, 12, 0))
    sch = _scheduler(tmp_path, clock, zone="Australia/Sydney", time="02:30")
    runs, _, _ = await _drive(sch, clock, until=_utc(2026, 10, 5, 0, 0), monkeypatch=monkeypatch)
    local = [r.astimezone(SYDNEY).isoformat(timespec="minutes") for r in runs]
    assert local == [
        "2026-10-03T02:30+10:00",
        "2026-10-04T03:30+11:00",  # shifted forward by the gap, run once
        "2026-10-05T02:30+11:00",
    ]


@pytest.mark.asyncio
async def test_loop_does_not_repeat_a_run_at_fall_back(tmp_path, monkeypatch) -> None:
    clock = _Clock(_utc(2026, 4, 3, 12, 0))
    sch = _scheduler(tmp_path, clock, zone="Australia/Sydney", time="02:30")
    runs, _, wakes = await _drive(sch, clock, until=_utc(2026, 4, 6, 0, 0), monkeypatch=monkeypatch)
    assert runs == [
        _utc(2026, 4, 3, 15, 30),  # 02:30+11:00 on the 4th
        _utc(2026, 4, 4, 15, 30),  # the first 02:30 on the 5th
        _utc(2026, 4, 5, 16, 30),  # 02:30+10:00 on the 6th; the second 02:30 never runs
    ]
    # The loop did wake during the repeated hour (fold=1) and ran nothing then.
    repeated_wakes = [w for w in wakes if w.astimezone(SYDNEY).fold == 1]
    assert repeated_wakes
    assert not any(r in repeated_wakes for r in runs)


@pytest.mark.asyncio
async def test_loop_runs_a_04_00_schedule_once_on_each_transition_day(
    tmp_path, monkeypatch
) -> None:
    for start, until, expected in (
        (
            _utc(2026, 10, 2, 12, 0),
            _utc(2026, 10, 4, 12, 0),
            ["2026-10-03T04:00+10:00", "2026-10-04T04:00+11:00"],
        ),
        (
            _utc(2026, 4, 3, 12, 0),
            _utc(2026, 4, 5, 12, 0),
            ["2026-04-04T04:00+11:00", "2026-04-05T04:00+10:00"],
        ),
    ):
        clock = _Clock(start)
        sch = _scheduler(tmp_path, clock, zone="Australia/Sydney", time="04:00")
        runs, _, _ = await _drive(sch, clock, until=until, monkeypatch=monkeypatch)
        assert [r.astimezone(SYDNEY).isoformat(timespec="minutes") for r in runs] == expected


@pytest.mark.asyncio
async def test_sleep_delay_across_a_transition_is_the_true_utc_difference(
    tmp_path, monkeypatch
) -> None:
    # 13:30Z on 4 April is 00:30+11:00 on the 5th. The next 04:00 is 04:00+10:00,
    # so the wall clock moves 3h30 but the real wait is 4h30.
    clock = _Clock(_utc(2026, 4, 4, 13, 30))
    sch = _scheduler(tmp_path, clock, zone="Australia/Sydney", time="04:00")
    _, delays, _ = await _drive(
        sch, clock, until=_utc(2026, 4, 4, 13, 31), monkeypatch=monkeypatch, max_sleep=1e9
    )
    assert delays[0] == 4.5 * 3600


# -- 2.4 live zone change -----------------------------------------
@pytest.mark.asyncio
async def test_changing_the_zone_recomputes_the_next_run_and_wakes_the_loop(tmp_path) -> None:
    clock = _Clock(_utc(2026, 10, 6, 12, 0))
    sch = _scheduler(tmp_path, clock, zone="UTC", time="04:00")
    assert sch.backup_next_run() == _utc(2026, 10, 7, 4, 0)
    sch._wake.clear()

    sch._cobble_settings.set_timezone("Australia/Brisbane")

    assert sch.backup_next_run() == _utc(2026, 10, 6, 18, 0)
    assert sch._wake.is_set()
