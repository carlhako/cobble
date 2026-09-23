"""Task 1.2: ``ScheduleConfig`` validation."""

from __future__ import annotations

import pytest

from cobble.maintenance.schedule_config import (
    ScheduleConfig,
    ScheduleValidationError,
    parse_hhmm,
)


def test_parse_hhmm() -> None:
    assert parse_hhmm("04:00") == (4, 0)
    assert parse_hhmm("23:59") == (23, 59)
    assert parse_hhmm("") is None
    assert parse_hhmm("24:00") is None
    assert parse_hhmm("nope") is None


def test_valid_daily() -> None:
    cfg = ScheduleConfig.from_dict({"enabled": True, "time": "04:00", "frequency": "daily"})
    assert cfg == ScheduleConfig(enabled=True, time="04:00", frequency="daily", day=None)


def test_valid_weekly() -> None:
    cfg = ScheduleConfig.from_dict(
        {"enabled": True, "time": "04:00", "frequency": "weekly", "day": 6}
    )
    assert cfg.day == 6


def test_valid_monthly() -> None:
    cfg = ScheduleConfig.from_dict(
        {"enabled": True, "time": "04:00", "frequency": "monthly", "day": 31}
    )
    assert cfg.day == 31


@pytest.mark.parametrize(
    "data",
    [
        {"enabled": "yes", "time": "04:00", "frequency": "daily"},
        {"enabled": True, "time": "25:00", "frequency": "daily"},
        {"enabled": True, "time": "04:00", "frequency": "yearly"},
        {"enabled": True, "time": "04:00", "frequency": "weekly", "day": 7},
        {"enabled": True, "time": "04:00", "frequency": "weekly", "day": -1},
        {"enabled": True, "time": "04:00", "frequency": "weekly"},  # missing day
        {"enabled": True, "time": "04:00", "frequency": "monthly", "day": 0},
        {"enabled": True, "time": "04:00", "frequency": "monthly", "day": 32},
        "not a dict",
    ],
)
def test_invalid_inputs_rejected(data) -> None:
    with pytest.raises(ScheduleValidationError):
        ScheduleConfig.from_dict(data)


def test_daily_ignores_day() -> None:
    cfg = ScheduleConfig.from_dict(
        {"enabled": True, "time": "04:00", "frequency": "daily", "day": 99}
    )
    assert cfg.day is None
