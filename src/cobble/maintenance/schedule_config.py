"""The shared schedule shape (``ScheduleConfig``) and its validation.

Used by the maintenance-settings overlay for both the backup and the
update-check schedule, and by :mod:`cobble.schedule` for the next-run maths.
"""

from __future__ import annotations

from dataclasses import dataclass

_FREQUENCIES = ("daily", "weekly", "monthly")


class ScheduleValidationError(ValueError):
    """A schedule (or another maintenance setting) failed validation."""


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


@dataclass(frozen=True)
class ScheduleConfig:
    """One recurring schedule: whether it runs at all, at what local wall-clock
    time, and how often.

    ``day`` is ignored for ``daily``, a weekday (0=Monday .. 6=Sunday, matching
    ``datetime.date.weekday()``) for ``weekly``, and a day-of-month (1-31) for
    ``monthly`` — a day-of-month beyond a given month's length clamps to that
    month's last day (maintenance-settings spec) rather than skipping the month.
    """

    enabled: bool
    time: str  # "HH:MM", 24h
    frequency: str  # daily | weekly | monthly
    day: int | None = None

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "time": self.time,
            "frequency": self.frequency,
            "day": self.day,
        }

    @classmethod
    def from_dict(cls, data: object) -> ScheduleConfig:
        if not isinstance(data, dict):
            raise ScheduleValidationError("a schedule must be an object")

        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise ScheduleValidationError("schedule.enabled must be a boolean")

        time_s = data.get("time")
        if not isinstance(time_s, str) or parse_hhmm(time_s) is None:
            raise ScheduleValidationError("schedule.time must be a 24-hour HH:MM time")

        frequency = data.get("frequency")
        if frequency not in _FREQUENCIES:
            raise ScheduleValidationError(
                "schedule.frequency must be one of 'daily', 'weekly', 'monthly'"
            )

        raw_day = data.get("day")
        day: int | None
        if frequency == "daily":
            day = None
        elif frequency == "weekly":
            if not isinstance(raw_day, int) or isinstance(raw_day, bool) or not (0 <= raw_day <= 6):
                raise ScheduleValidationError(
                    "a weekly schedule.day must be an integer 0-6 (Monday-Sunday)"
                )
            day = raw_day
        else:  # monthly
            if (
                not isinstance(raw_day, int)
                or isinstance(raw_day, bool)
                or not (1 <= raw_day <= 31)
            ):
                raise ScheduleValidationError("a monthly schedule.day must be an integer 1-31")
            day = raw_day

        return cls(enabled=enabled, time=time_s, frequency=frequency, day=day)
