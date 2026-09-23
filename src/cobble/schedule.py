"""In-process maintenance scheduler (section 7, design.md D7/D10; reworked for
independent backup/update schedules, design.md "Decisions" #1-#2).

An asyncio task computes each schedule's own next run in local wall-clock time
and sleeps until the earlier of the two, waking early if a settings write
calls :meth:`Scheduler.reschedule_now`. When both schedules are due together
(within the jitter grace) they run as one ordered sequence — backup first,
then the update check/apply — under a single maintenance scope, so the server
is stopped at most once (server-backups / server-updates specs). When only one
is due, it runs alone through the same underlying service methods.

A window missed because cobble was down at the scheduled time is simply
skipped; the next run is the following occurrence. There is no catch-up —
waking hours later and stopping the server at an unexpected time is worse than
waiting for the next scheduled run. On-demand backup and update reuse the same
sequence (``run_now``).
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
from collections.abc import Callable
from datetime import datetime, timedelta

from cobble.backup.service import BackupService
from cobble.logging import get_logger
from cobble.maintenance.schedule_config import ScheduleConfig, parse_hhmm
from cobble.maintenance.service import MaintenanceSettingsService
from cobble.maintenance.settings_store import MaintenanceSettingsStore
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor
from cobble.update.service import UpdateService

log = get_logger("schedule")

__all__ = ["Scheduler", "parse_hhmm"]

# The scheduler wakes at least this often to re-evaluate the next run, so a
# config change or a DST shift is picked up without a restart.
_MAX_SLEEP = 900.0
# Absorbs event-loop jitter: a wake-up within this margin *after* the target
# still runs that window. It is not catch-up — once we are further past the
# target than this, the window is skipped until the next occurrence.
_JITTER_GRACE = timedelta(minutes=30)


def _clamp_day(year: int, month: int, day: int) -> int:
    """A day-of-month beyond a given month's length clamps to that month's
    last day (maintenance-settings spec), so a fixed "31" still fires monthly
    instead of silently skipping short months."""
    last = calendar.monthrange(year, month)[1]
    return min(day, last)


def _monthly_at(year: int, month: int, day: int, hh: int, mm: int) -> datetime:
    return datetime(year, month, _clamp_day(year, month, day), hh, mm)


def _next_after(cfg: ScheduleConfig, now: datetime) -> datetime | None:
    """The next local wall-clock time ``cfg`` fires after ``now``, or ``None``
    if ``cfg.time`` is unparseable (a defensively-tolerated corrupt overlay)."""
    parsed = parse_hhmm(cfg.time)
    if parsed is None:
        log.warning("schedule has an invalid time %r; treating it as having no next run", cfg.time)
        return None
    hh, mm = parsed

    if cfg.frequency == "daily":
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)

    if cfg.frequency == "weekly":
        day = cfg.day if cfg.day is not None else 0  # 0=Monday .. 6=Sunday
        base = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        days_ahead = (day - base.weekday()) % 7
        candidate = base + timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    if cfg.frequency == "monthly":
        day = cfg.day if cfg.day is not None else 1
        candidate = _monthly_at(now.year, now.month, day, hh, mm)
        if candidate <= now:
            y, m = now.year, now.month + 1
            if m > 12:
                m = 1
                y += 1
            candidate = _monthly_at(y, m, day, hh, mm)
        return candidate

    log.warning(
        "schedule has an unknown frequency %r; treating it as having no next run", cfg.frequency
    )
    return None


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        backup: BackupService,
        update: UpdateService,
        *,
        supervisor: Supervisor | None = None,
        maintenance_settings: MaintenanceSettingsService | None = None,
        clock: Callable[[], datetime] = datetime.now,  # naive local time
    ) -> None:
        self._settings = settings
        self._backup = backup
        self._update = update
        # Only needed for the coordinated window (task 2.3), to stop/start the
        # server exactly once around both operations. Falls back to the
        # backup service's own supervisor when not given explicitly (they are
        # always the same instance in production wiring).
        self._sup = supervisor or backup._sup
        # Callers that don't care about the overlay (most existing wiring and
        # tests) get a service backed by an empty store — equivalent to
        # reading ``Settings`` directly (task 2.1).
        self._maintenance_settings = maintenance_settings or MaintenanceSettingsService(
            MaintenanceSettingsStore(settings.state_dir / "maintenance_settings.json"), settings
        )
        self._maintenance_settings.set_on_change(self.reschedule_now)
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._window_lock = asyncio.Lock()
        # Lets a settings write wake the loop immediately to recompute its
        # sleep, instead of waiting up to `_MAX_SLEEP` (task 2.4).
        self._wake = asyncio.Event()

    # -- schedule maths ---------------------------------------
    def backup_next_run(self) -> datetime | None:
        """The next local wall-clock time a scheduled backup will run, or
        ``None`` when the backup schedule is disabled."""
        return self._backup_next_after(self._clock())

    def update_next_run(self) -> datetime | None:
        """The next local wall-clock time a scheduled update check will run,
        or ``None`` when the update schedule is disabled."""
        return self._update_next_after(self._clock())

    def _backup_next_after(self, after: datetime) -> datetime | None:
        if not self._maintenance_settings.effective_backup_enabled():
            return None
        return _next_after(self._maintenance_settings.effective_backup_schedule(), after)

    def _update_next_after(self, after: datetime) -> datetime | None:
        cfg = self._maintenance_settings.effective_update_schedule()
        if not cfg.enabled:
            return None
        return _next_after(cfg, after)

    def next_run(self) -> datetime | None:
        """The earlier of the two schedules' next runs, or ``None`` if both
        are disabled."""
        candidates = [t for t in (self.backup_next_run(), self.update_next_run()) if t is not None]
        return min(candidates) if candidates else None

    def _should_run(self, target: datetime, now: datetime) -> bool:
        """Run ``target``'s window iff we have reached it and are not so far
        past it that the window should be skipped until its next occurrence."""
        return target <= now <= target + _JITTER_GRACE

    def _is_due(self, target: datetime, now: datetime, deferred_from: datetime | None) -> bool:
        """``_should_run``, except that an occurrence which fell while our own
        previous window was running (at or after ``deferred_from``) still runs
        however long that window took — it was delayed, not missed."""
        if deferred_from is not None and deferred_from <= target <= now:
            return True
        return self._should_run(target, now)

    # -- lifecycle ------------------------------------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="cobble-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    def reschedule_now(self) -> None:
        """Wake the loop immediately to recompute its sleep against the
        current settings (task 2.4) — called after a maintenance-settings
        write so an edited schedule takes effect without a restart."""
        self._wake.set()

    async def _sleep_until(self, seconds: float) -> None:
        self._wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=max(0.0, seconds))

    async def _loop(self) -> None:
        # Next runs are computed after ``cursor`` — the last time the loop
        # evaluated due-ness — not after "now". Otherwise an occurrence that
        # fell while a window was running (e.g. an update check at 03:05
        # during a 03:00 backup that takes ten minutes) would be pushed to its
        # next occurrence and silently skipped.
        cursor = self._clock()
        deferred_from: datetime | None = None
        try:
            while True:
                b_next = self._backup_next_after(cursor)
                u_next = self._update_next_after(cursor)
                candidates = [t for t in (b_next, u_next) if t is not None]
                if not candidates:
                    await self._sleep_until(_MAX_SLEEP)
                    cursor, deferred_from = self._clock(), None
                    continue
                nxt = min(candidates)
                delay = (nxt - self._clock()).total_seconds()
                await self._sleep_until(min(delay, _MAX_SLEEP))

                now = self._clock()
                backup_due = b_next is not None and self._is_due(b_next, now, deferred_from)
                update_due = u_next is not None and self._is_due(u_next, now, deferred_from)
                cursor, deferred_from = now, None
                if backup_due or update_due:
                    await self._run_window(
                        reason="scheduled", want_backup=backup_due, want_update=update_due
                    )
                    # Anything that came due while the window ran is run next
                    # iteration, regardless of the jitter grace.
                    deferred_from = now
                # Otherwise: either the sleep was clamped/interrupted and we
                # are not there yet (loop recomputes a shorter delay), or we
                # woke so late the window is skipped until its next occurrence.
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler loop crashed; scheduled maintenance is stopped")

    # -- the window ----------------------------------------
    async def run_now(self) -> None:
        """Run the maintenance sequence on demand (task 7.4), honouring
        whichever of the two schedules are currently enabled."""
        await self._run_window(reason="manual", want_backup=True, want_update=True)

    async def _run_window(self, *, reason: str, want_backup: bool, want_update: bool) -> None:
        if self._window_lock.locked():
            log.info("maintenance window already running; skipping the %s trigger", reason)
            return
        async with self._window_lock:
            do_backup = want_backup and self._maintenance_settings.effective_backup_enabled()
            do_update_check = (
                want_update and self._maintenance_settings.effective_update_schedule().enabled
            )
            if not do_backup and not do_update_check:
                return

            log.info("maintenance window starting (%s)", reason)

            update_applicable = False
            if do_update_check:
                try:
                    check = await self._update.check()
                except Exception:
                    log.exception("scheduled update check failed")
                    check = None
                update_applicable = bool(
                    check is not None
                    and check.available
                    and not check.up_to_date
                    and not check.skipped
                    and not check.error
                )
                if check is not None and check.skipped:
                    log.info("scheduled update skipped: %s", check.skipped_reason)

            if do_backup and update_applicable:
                # Coincide: one coordinated window, backup first, single
                # stop/start (task 2.3; server-backups/server-updates specs).
                await self._run_coordinated(reason)
            elif update_applicable:
                try:
                    await self._update.apply(reason=reason)
                except Exception:
                    log.exception("scheduled update failed")
            elif do_backup:
                try:
                    await self._backup.capture(reason=reason)
                except Exception:
                    log.exception("scheduled backup failed")

            log.info("maintenance window complete (%s)", reason)

    async def _run_coordinated(self, reason: str) -> None:
        """Backup, then update, under one maintenance scope so the server is
        stopped at most once (task 2.3)."""
        sup = self._sup
        async with sup.maintenance_scope("updating") as handle:
            was_running = sup.state is RunState.RUNNING
            if was_running:
                handle.set_step("stopping server")
                await sup.maintenance_stop(reason="scheduled maintenance")

            handle.set_step(f"capturing {reason} backup")
            try:
                await self._backup.snapshot_now(reason)
            except Exception:
                log.exception("scheduled backup failed")

            result = None
            try:
                result = await self._update.apply_coordinated(
                    handle=handle, was_running=was_running, reason=reason
                )
            except Exception:
                log.exception("scheduled update failed")

            # `apply_coordinated` already leaves the server in its final
            # run-state (running on success/rollback, deliberately stopped on
            # a terminal failure) whenever it actually attempted an update. It
            # returns `None` when there was nothing to apply after all (a race
            # against the earlier check, e.g. it became up to date or was
            # quarantined) — in that case nobody has restarted the server yet.
            if result is None and was_running and not sup.is_closing:
                handle.set_step("starting server")
                await sup.maintenance_start()
