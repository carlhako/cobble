"""In-process nightly maintenance scheduler (section 7, design.md D7/D10).

An asyncio task computes the next run in local wall-clock time and sleeps until
it. The nightly window is one ordered sequence — a scheduled backup, then an
update check that applies an available update — so the server is stopped at most
once when both are due (task 7.2).

A window missed because cobble was down at the scheduled time is simply skipped;
the next run is the following day's window. There is no catch-up — waking hours
later and stopping the server at an unexpected time is worse than waiting one
day for the next scheduled backup. The schedule is configurable and disableable;
on-demand backup and update reuse the same sequence (7.3, 7.4).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import datetime, timedelta

from cobble.backup.service import BackupService
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.update.service import UpdateService

log = get_logger("schedule")

# The scheduler wakes at least this often to re-evaluate the next run, so a
# config change or a DST shift is picked up without a restart.
_MAX_SLEEP = 900.0
# Absorbs event-loop jitter: a wake-up within this margin *after* the target
# still runs that window. It is not catch-up — once we are further past the
# target than this, the window is skipped until the next day.
_JITTER_GRACE = timedelta(minutes=30)


def parse_hhmm(value: str) -> tuple[int, int] | None:
    value = value.strip()
    if not value:
        return None
    try:
        h, m = value.split(":", 1)
        hh, mm = int(h), int(m)
    except (ValueError, IndexError):
        return None
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return hh, mm
    return None


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        backup: BackupService,
        update: UpdateService,
        *,
        clock: Callable[[], datetime] = datetime.now,  # naive local time
    ) -> None:
        self._settings = settings
        self._backup = backup
        self._update = update
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._window_lock = asyncio.Lock()

    # -- schedule maths ---------------------------------------
    def _enabled(self) -> bool:
        return parse_hhmm(self._settings.maintenance_time) is not None and (
            self._settings.backup_enabled or self._settings.update_enabled
        )

    def next_run(self) -> datetime | None:
        """The next local wall-clock time the window will run, or ``None`` when
        the schedule is disabled (task 7.3)."""
        if not self._enabled():
            return None
        return self._next_after(self._clock())

    def _next_after(self, now: datetime) -> datetime:
        hh, mm = parse_hhmm(self._settings.maintenance_time)  # type: ignore[misc]
        today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return today if today > now else today + timedelta(days=1)

    def _should_run(self, target: datetime, now: datetime) -> bool:
        """Run ``target``'s window iff we have reached it and are not so far
        past it that the window should be skipped until the next day."""
        return target <= now <= target + _JITTER_GRACE

    # -- lifecycle ------------------------------------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="cobble-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        try:
            while True:
                nxt = self.next_run()
                if nxt is None:
                    await asyncio.sleep(_MAX_SLEEP)
                    continue
                delay = (nxt - self._clock()).total_seconds()
                await asyncio.sleep(max(0.0, min(delay, _MAX_SLEEP)))
                if self._should_run(nxt, self._clock()):
                    await self._run_window(reason="scheduled")
                # Otherwise: either the sleep was clamped and we are not there
                # yet (loop recomputes a shorter delay), or we woke so late the
                # window is skipped until tomorrow.
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler loop crashed; scheduled maintenance is stopped")

    # -- the window ----------------------------------------
    async def run_now(self) -> None:
        """Run the nightly sequence on demand (task 7.4)."""
        await self._run_window(reason="manual")

    async def _run_window(self, *, reason: str) -> None:
        if self._window_lock.locked():
            log.info("maintenance window already running; skipping the %s trigger", reason)
            return
        async with self._window_lock:
            log.info("maintenance window starting (%s)", reason)

            did_update_backup = False
            if self._settings.update_enabled:
                try:
                    check = await self._update.check()
                except Exception:
                    log.exception("scheduled update check failed")
                    check = None
                if (
                    check is not None
                    and check.available
                    and not check.up_to_date
                    and not check.skipped
                    and not check.error
                ):
                    log.info("scheduled update: %s -> %s", check.installed, check.available)
                    try:
                        result = await self._update.apply(reason="scheduled")
                        # the update's verified pre-update backup covers tonight's backup
                        did_update_backup = result.status in (
                            "success",
                            "rolled_back",
                            "terminal",
                        )
                    except Exception:
                        log.exception("scheduled update failed")
                elif check is not None and check.skipped:
                    log.info("scheduled update skipped: %s", check.skipped_reason)

            if self._settings.backup_enabled and not did_update_backup:
                try:
                    await self._backup.capture(reason="scheduled")
                except Exception:
                    log.exception("scheduled backup failed")

            log.info("maintenance window complete (%s)", reason)
