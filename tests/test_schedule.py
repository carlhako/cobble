"""Section 2: the decoupled backup/update-check scheduler (tasks 2.1-2.5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from cobble.backup.service import BackupService
from cobble.maintenance.schedule_config import ScheduleConfig
from cobble.maintenance.service import MaintenanceSettingsService
from cobble.maintenance.settings_store import MaintenanceSettingsStore
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


def _msvc(
    tmp_path,
    settings: Settings,
    *,
    backup_schedule: ScheduleConfig | None = None,
    update_schedule: ScheduleConfig | None = None,
) -> MaintenanceSettingsService:
    store = MaintenanceSettingsStore(tmp_path / "maintenance_settings.json")
    if backup_schedule is not None:
        store.set(backup_schedule=backup_schedule)
    if update_schedule is not None:
        store.set(update_schedule=update_schedule)
    return MaintenanceSettingsService(store, settings)


def _scheduler(tmp_path, settings, backup, update, *, clock, msvc=None) -> Scheduler:
    return Scheduler(
        settings,
        backup,
        update,
        supervisor=SimpleNamespace(),  # unused unless a coordinated window runs
        maintenance_settings=msvc or _msvc(tmp_path, settings),
        clock=clock,
    )


# -- 1.2 / 2.1 schedule maths --------------------------------------
async def test_parse_hhmm() -> None:
    assert parse_hhmm("04:00") == (4, 0)
    assert parse_hhmm("23:59") == (23, 59)
    assert parse_hhmm("") is None
    assert parse_hhmm("24:00") is None
    assert parse_hhmm("nope") is None


async def test_daily_next_run_is_todays_or_tomorrows_local_time(tmp_path) -> None:
    clock = _Clock(datetime(2026, 6, 1, 3, 30))  # before 04:00
    sch = _scheduler(
        tmp_path, _settings(tmp_path), _StubBackup(), _StubUpdate(_check()), clock=clock
    )
    assert sch.backup_next_run() == datetime(2026, 6, 1, 4, 0)
    assert sch.update_next_run() == datetime(2026, 6, 1, 4, 0)

    clock.now = datetime(2026, 6, 1, 4, 30)  # after 04:00
    assert sch.backup_next_run() == datetime(2026, 6, 2, 4, 0)


async def test_next_run_tracks_wall_clock_across_a_dst_jump(tmp_path) -> None:
    clock = _Clock(datetime(2026, 3, 7, 23, 0))
    sch = _scheduler(
        tmp_path, _settings(tmp_path), _StubBackup(), _StubUpdate(_check()), clock=clock
    )
    assert sch.backup_next_run() == datetime(2026, 3, 8, 4, 0)
    clock.now = datetime(2026, 3, 8, 3, 15)
    assert sch.backup_next_run() == datetime(2026, 3, 8, 4, 0)


async def test_disabled_schedule_reports_no_next_run(tmp_path) -> None:
    settings = _settings(tmp_path, maintenance_time="")
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 1, 3, 0)),
    )
    assert sch.backup_next_run() is None
    assert sch.update_next_run() is None
    assert sch.next_run() is None

    settings2 = _settings(tmp_path, backup_enabled=False, update_enabled=False)
    sch2 = _scheduler(
        tmp_path,
        settings2,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 1, 3, 0)),
    )
    assert sch2.backup_next_run() is None
    assert sch2.update_next_run() is None


async def test_each_schedule_can_be_disabled_independently(tmp_path) -> None:
    # Backup's on/off is the top-level `backup_enabled` flag (mirrored into
    # its schedule's `enabled`); the update schedule carries its own
    # independent `enabled` since there is no separate `update_enabled`
    # overlay field (design.md Decisions #4).
    settings = _settings(tmp_path)
    store = MaintenanceSettingsStore(tmp_path / "maintenance_settings.json")
    store.set(backup_enabled=False)
    store.set(update_schedule=ScheduleConfig(enabled=True, time="05:00", frequency="daily"))
    msvc = MaintenanceSettingsService(store, settings)
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 1, 3, 0)),
        msvc=msvc,
    )
    assert sch.backup_next_run() is None
    assert sch.update_next_run() == datetime(2026, 6, 1, 5, 0)


# -- 2.1 weekly / monthly frequencies, clamping ----------------------
async def test_weekly_schedule_runs_on_the_chosen_weekday(tmp_path) -> None:
    settings = _settings(tmp_path)
    # 2026-06-01 is a Monday (weekday 0); target Thursday (3).
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="weekly", day=3),
    )
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 1, 0, 0)),
        msvc=msvc,
    )
    assert sch.backup_next_run() == datetime(2026, 6, 4, 4, 0)  # the following Thursday


async def test_weekly_schedule_recurs_after_it_passes(tmp_path) -> None:
    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="weekly", day=3),
    )
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 4, 5, 0)),  # just past this week's run
        msvc=msvc,
    )
    assert sch.backup_next_run() == datetime(2026, 6, 11, 4, 0)


async def test_monthly_schedule_runs_on_the_chosen_day(tmp_path) -> None:
    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="monthly", day=15),
    )
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 1, 0, 0)),
        msvc=msvc,
    )
    assert sch.backup_next_run() == datetime(2026, 6, 15, 4, 0)


async def test_monthly_schedule_day_31_clamps_in_a_30_day_month(tmp_path) -> None:
    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="monthly", day=31),
    )
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 4, 1, 0, 0)),
        msvc=msvc,
    )
    assert sch.backup_next_run() == datetime(2026, 4, 30, 4, 0)  # April has 30 days


async def test_monthly_schedule_day_31_clamps_in_february(tmp_path) -> None:
    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="monthly", day=31),
    )
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 2, 1, 0, 0)),
        msvc=msvc,
    )
    assert sch.backup_next_run() == datetime(2026, 2, 28, 4, 0)  # 2026 is not a leap year


async def test_monthly_schedule_day_29_clamps_in_february_of_a_leap_year(tmp_path) -> None:
    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="monthly", day=30),
    )
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2028, 2, 1, 0, 0)),
        msvc=msvc,
    )
    assert sch.backup_next_run() == datetime(2028, 2, 29, 4, 0)  # 2028 is a leap year


async def test_monthly_schedule_recurs_next_month_after_it_passes(tmp_path) -> None:
    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="monthly", day=15),
    )
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 20, 0, 0)),
        msvc=msvc,
    )
    assert sch.backup_next_run() == datetime(2026, 7, 15, 4, 0)


# -- 2.1 independent per-schedule next-run --------------------------
async def test_backup_and_update_schedules_are_independent(tmp_path) -> None:
    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="daily"),
        update_schedule=ScheduleConfig(enabled=True, time="04:00", frequency="weekly", day=6),
    )
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check()),
        clock=_Clock(datetime(2026, 6, 1, 0, 0)),
        msvc=msvc,
    )
    assert sch.backup_next_run() == datetime(2026, 6, 1, 4, 0)
    assert sch.update_next_run() == datetime(2026, 6, 7, 4, 0)  # the next Sunday
    assert sch.next_run() == datetime(2026, 6, 1, 4, 0)  # the earlier of the two


# -- 2.2 / 2.3 window sequencing (non-coinciding via stubs) ---------
async def test_window_with_an_available_update_and_no_due_backup_runs_update_only(
    tmp_path,
) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1"))
    sch = _scheduler(
        tmp_path, _settings(tmp_path), backup, update, clock=_Clock(datetime(2026, 6, 1, 4, 1))
    )
    await sch._run_window(reason="scheduled", want_backup=False, want_update=True)
    assert update.applied == ["scheduled"]
    assert backup.captured == []


async def test_window_with_a_due_backup_and_no_due_update_runs_backup_only(tmp_path) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(up_to_date=True))
    sch = _scheduler(
        tmp_path, _settings(tmp_path), backup, update, clock=_Clock(datetime(2026, 6, 1, 4, 1))
    )
    await sch._run_window(reason="scheduled", want_backup=True, want_update=False)
    assert update.checks == 0
    assert backup.captured == ["scheduled"]


async def test_window_skips_the_update_for_a_quarantined_version_but_still_backs_up(
    tmp_path,
) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1", skipped=True))
    sch = _scheduler(
        tmp_path, _settings(tmp_path), backup, update, clock=_Clock(datetime(2026, 6, 1, 4, 1))
    )
    await sch._run_window(reason="scheduled", want_backup=True, want_update=True)
    assert update.applied == []
    assert backup.captured == ["scheduled"]


async def test_backup_only_schedule_never_checks_for_updates(tmp_path) -> None:
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1"))
    settings = _settings(tmp_path, update_enabled=False)
    sch = _scheduler(tmp_path, settings, backup, update, clock=_Clock(datetime(2026, 6, 1, 4, 1)))
    await sch._run_window(reason="scheduled", want_backup=True, want_update=True)
    assert update.checks == 0
    assert backup.captured == ["scheduled"]


# -- 2.1 a missed window is skipped, not caught up -----------
async def test_missed_window_is_skipped_until_the_next_occurrence(tmp_path) -> None:
    clock = _Clock(datetime(2026, 6, 1, 5, 0))
    sch = _scheduler(
        tmp_path,
        _settings(tmp_path),
        _StubBackup(),
        _StubUpdate(_check(up_to_date=True)),
        clock=clock,
    )
    assert sch.backup_next_run() == datetime(2026, 6, 2, 4, 0)  # tomorrow, not "now"
    assert sch._should_run(datetime(2026, 6, 1, 4, 0), clock()) is False


async def test_should_run_only_within_the_jitter_grace_after_the_target(tmp_path) -> None:
    sch = _scheduler(
        tmp_path,
        _settings(tmp_path),
        _StubBackup(),
        _StubUpdate(_check(up_to_date=True)),
        clock=_Clock(datetime(2026, 6, 1, 4, 0)),
    )
    target = datetime(2026, 6, 1, 4, 0)
    assert sch._should_run(target, datetime(2026, 6, 1, 3, 59, 59)) is False  # not yet
    assert sch._should_run(target, datetime(2026, 6, 1, 4, 0, 1)) is True  # on time
    assert sch._should_run(target, datetime(2026, 6, 1, 4, 25)) is True  # small jitter
    assert sch._should_run(target, datetime(2026, 6, 1, 4, 45)) is False  # woke too late


async def test_no_schedule_state_file_is_written(tmp_path) -> None:
    s = _settings(tmp_path)
    sch = _scheduler(
        tmp_path,
        s,
        _StubBackup(),
        _StubUpdate(_check(up_to_date=True)),
        clock=_Clock(datetime(2026, 6, 1, 4, 1)),
    )
    await sch.run_now()
    assert not (s.state_dir / "schedule.json").exists()


# -- 7.4 / 2.3 on-demand reuses the sequence -----------------
async def test_run_now_uses_the_same_sequence_regardless_of_time(tmp_path) -> None:
    # Backup disabled here so the update leg runs standalone (through the same
    # `_update.apply` path a lone due update uses) rather than the coordinated
    # path, which needs a real supervisor — covered separately below.
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1"))
    settings = _settings(tmp_path, backup_enabled=False)
    sch = _scheduler(tmp_path, settings, backup, update, clock=_Clock(datetime(2026, 6, 1, 14, 0)))
    await sch.run_now()
    assert update.applied == ["manual"]
    assert backup.captured == []


# -- 2.4 reschedule wakes the loop immediately -----------------------
async def test_reschedule_now_wakes_a_sleeping_loop(tmp_path) -> None:
    settings = _settings(tmp_path)
    msvc = _msvc(tmp_path, settings)
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check(up_to_date=True)),
        clock=_Clock(datetime(2026, 6, 1, 0, 0)),
        msvc=msvc,
    )
    # Not started as a real loop here — just prove the event is set/cleared
    # correctly around a manual wait, mirroring what `_loop` does each cycle.
    import asyncio

    async def _wait_briefly():
        return await asyncio.wait_for(sch._wake.wait(), timeout=2)

    task = asyncio.ensure_future(_wait_briefly())
    await asyncio.sleep(0.01)
    sch.reschedule_now()
    result = await task
    assert result is True


async def test_maintenance_settings_write_reschedules_via_the_service_callback(tmp_path) -> None:
    settings = _settings(tmp_path)
    store = MaintenanceSettingsStore(tmp_path / "maintenance_settings.json")
    msvc = MaintenanceSettingsService(store, settings)
    sch = _scheduler(
        tmp_path,
        settings,
        _StubBackup(),
        _StubUpdate(_check(up_to_date=True)),
        clock=_Clock(datetime(2026, 6, 1, 0, 0)),
        msvc=msvc,
    )
    assert sch._wake.is_set() is False
    msvc.write({"backup_retention": 10})
    assert sch._wake.is_set() is True


# -- 2.3 a coordinated window stops the server exactly once ----------
@pytest.mark.parametrize("reason", ["scheduled", "manual"])
async def test_coordinated_window_stops_the_server_at_most_once(make_supervisor, reason) -> None:
    import stat
    import sys
    from pathlib import Path

    from cobble.acquisition.layout import Layout
    from cobble.acquisition.version_source import ResolvedVersion
    from cobble.update.service import UpdateService

    fake_bedrock = Path(__file__).parent / "supervisor" / "fake_bedrock.py"
    good = f'#!/bin/sh\nexec "{sys.executable}" "{fake_bedrock}" "$@"\n'

    def _write_binary(vdir, script: str) -> None:
        vdir.mkdir(parents=True, exist_ok=True)
        b = vdir / "bedrock_server"
        b.write_text(script)
        b.chmod(b.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    def _fake_install(resolved, layout, settings) -> None:
        _write_binary(layout.version_dir(resolved.version), good)

    sup = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    sup._settings = sup._settings.model_copy(update={"update_grace_seconds": 0.3})
    layout = Layout.from_settings(sup._settings)
    backup = BackupService(sup._settings, layout, sup)
    update = UpdateService(
        sup._settings,
        layout,
        sup,
        backup,
        resolver=lambda _s: ResolvedVersion("2.0.0.1", "http://vendor/x.zip"),
    )

    import cobble.update.service as service_mod

    orig_install = service_mod.install_version
    service_mod.install_version = _fake_install
    try:
        await sup.start()
        stop_calls = []
        start_calls = []
        orig_stop = sup.maintenance_stop
        orig_start = sup.maintenance_start

        async def _counted_stop(*a, **kw):
            stop_calls.append(1)
            return await orig_stop(*a, **kw)

        async def _counted_start(*a, **kw):
            start_calls.append(1)
            return await orig_start(*a, **kw)

        sup.maintenance_stop = _counted_stop
        sup.maintenance_start = _counted_start

        sch = Scheduler(sup._settings, backup, update, supervisor=sup)
        await sch._run_window(reason=reason, want_backup=True, want_update=True)

        assert len(stop_calls) == 1  # stopped exactly once for the pair
        assert len(start_calls) == 1  # started exactly once
        assert len(backup.list_backups()) >= 1  # the scheduled backup ran
        # the window's own backup carries the window's trigger, not a fixed one
        assert [h.reason for h in backup.history()] == ["pre-update", reason]
        result = update.last_result
        assert result is not None and result.status == "success"
    finally:
        service_mod.install_version = orig_install
        if sup.state.name == "RUNNING":
            await sup.stop()


async def test_non_coinciding_runs_behave_independently(tmp_path) -> None:
    # A backup-only window never touches the update service at all.
    backup, update = _StubBackup(), _StubUpdate(_check(available="2.0.0.1"))
    sch = _scheduler(
        tmp_path, _settings(tmp_path), backup, update, clock=_Clock(datetime(2026, 6, 1, 4, 1))
    )
    await sch._run_window(reason="scheduled", want_backup=True, want_update=False)
    assert backup.captured == ["scheduled"]
    assert update.checks == 0
    assert update.applied == []


async def test_an_occurrence_that_falls_during_another_window_still_runs(tmp_path) -> None:
    # Backup at 03:00 takes 45 minutes (past the jitter grace); the 03:05 update
    # check comes due while it runs and must run straight after, not be pushed
    # to tomorrow.
    import asyncio

    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="03:00", frequency="daily"),
        update_schedule=ScheduleConfig(enabled=True, time="03:05", frequency="daily"),
    )
    clock = _Clock(datetime(2026, 6, 1, 2, 59))

    class _SlowBackup(_StubBackup):
        async def capture(self, *, reason: str) -> None:
            await super().capture(reason=reason)
            clock.advance(minutes=45)

    backup, update = _SlowBackup(), _StubUpdate(_check(available="2.0.0.1"))
    sch = _scheduler(tmp_path, settings, backup, update, clock=clock, msvc=msvc)

    sleeps = 0

    async def _fake_sleep(seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 6:
            raise asyncio.CancelledError
        clock.advance(seconds=max(0.0, seconds))

    sch._sleep_until = _fake_sleep  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await sch._loop()

    assert backup.captured == ["scheduled"]
    assert update.applied == ["scheduled"]


async def test_a_window_woken_too_late_is_still_skipped(tmp_path) -> None:
    # The deferral above only covers our own windows; a plain oversleep past
    # the jitter grace (e.g. host suspended) still skips, with no catch-up.
    import asyncio

    settings = _settings(tmp_path)
    msvc = _msvc(
        tmp_path,
        settings,
        backup_schedule=ScheduleConfig(enabled=True, time="03:00", frequency="daily"),
        update_schedule=ScheduleConfig(enabled=False, time="03:00", frequency="daily"),
    )
    clock = _Clock(datetime(2026, 6, 1, 2, 59))
    backup, update = _StubBackup(), _StubUpdate(_check(up_to_date=True))
    sch = _scheduler(tmp_path, settings, backup, update, clock=clock, msvc=msvc)

    sleeps = 0

    async def _fake_sleep(seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError
        clock.advance(hours=2)

    sch._sleep_until = _fake_sleep  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await sch._loop()

    assert backup.captured == []
