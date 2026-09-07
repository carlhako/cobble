"""In-process nightly maintenance scheduler (section 7, design.md D7/D10).

An asyncio task computes the next run in local wall-clock time and sleeps until
it. The nightly window is one ordered sequence — a scheduled backup, then an
update check that applies an available update — so the server is stopped at most
once when both are due (task 7.2). A window missed while cobble was down runs
once shortly after the next start (task 7.1). The schedule is configurable and
disableable; on-demand backup and update reuse the same sequences (7.3, 7.4).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from cobble.backup.service import BackupService
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.update.service import UpdateService

log = get_logger("schedule")

# The scheduler wakes at least this often to re-evaluate the next run, so a
# config change or a DST shift is picked up without a restart.
_MAX_SLEEP = 900.0
# A window that should have run within this margin of "now" still counts as due
# (covers a slightly late wake-up and the missed-window catch-up).
_DUE_MARGIN = timedelta(minutes=30)


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
        self._marker = settings.state_dir / "schedule.json"
        self._task: asyncio.Task[None] | None = None
        self._window_lock = asyncio.Lock()
        self._last_window: str | None = None  # ISO date of the last window run

    # -- schedule maths ---------------------------------------
    def _enabled(self) -> bool:
        return (
            parse_hhmm(self._settings.maintenance_time) is not None
            and (self._settings.backup_enabled or self._settings.update_enabled)
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

    def _missed_window(self, now: datetime) -> bool:
        """True when today's window time has passed, cobble was down for it, and
        it has not already run today."""
        hh, mm = parse_hhmm(self._settings.maintenance_time)  # type: ignore[misc]
        todays = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < todays:
            return False
        return self._last_window != now.date().isoformat()

    # -- persistence -----------------------------------------
    def _load_marker(self) -> None:
        try:
            self._last_window = json.loads(self._marker.read_text()).get("last_window")
        except (OSError, ValueError):
            self._last_window = None

    def _record_window(self, day: datetime) -> None:
        self._last_window = day.date().isoformat()
        self._marker.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._marker.with_suffix(".tmp")
        tmp.write_text(json.dumps({"last_window": self._last_window}))
        tmp.replace(self._marker)

    # -- lifecycle ------------------------------------------
    async def start(self) -> None:
        self._load_marker()
        self._task = asyncio.create_task(self._loop(), name="cobble-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        try:
            if self._enabled() and self._missed_window(self._clock()):
                log.info("a scheduled maintenance window was missed while down; running it now")
                await self._run_window(reason="catch-up")
            while True:
                nxt = self.next_run()
                if nxt is None:
                    await asyncio.sleep(_MAX_SLEEP)
                    continue
                delay = (nxt - self._clock()).total_seconds()
                await asyncio.sleep(max(0.0, min(delay, _MAX_SLEEP)))
                now = self._clock()
                if now >= nxt - _DUE_MARGIN and self._last_window != now.date().isoformat():
                    await self._run_window(reason="scheduled")
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
            now = self._clock()
            self._record_window(now)
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

    @property
    def marker_path(self) -> Path:
        return self._marker
