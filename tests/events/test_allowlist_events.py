"""Allowlist enforcement + membership events (tasks 2.1, 2.2)."""

from __future__ import annotations

from cobble.events.model import (
    AllowlistAdded,
    AllowlistDisabled,
    AllowlistEnabled,
    AllowlistRemoved,
    EventType,
)
from cobble.events.parser import parse_line

# Verbatim BDS 1.26.45.1 lines from design.md Context, with the real log prefix.
ON = "[2026-01-02 03:04:05:678 INFO] Turned on the allowlist"
OFF = "[2026-01-02 03:04:05:678 INFO] Turned off the allowlist"
ADDED = "[2026-01-02 03:04:05:678 INFO] Added Some Player With Spaces to the allowlist"
REMOVED = "[2026-01-02 03:04:05:678 INFO] Removed Some Player With Spaces from the allowlist"


# -- 2.1 enforcement announcements ---------------------------------
def test_turned_on_parses_and_retains_its_source_line() -> None:
    ev = parse_line(ON)
    assert isinstance(ev, AllowlistEnabled)
    assert ev.type is EventType.ALLOWLIST_ENABLED
    assert ev.raw == ON


def test_turned_off_parses_and_retains_its_source_line() -> None:
    ev = parse_line(OFF)
    assert isinstance(ev, AllowlistDisabled)
    assert ev.type is EventType.ALLOWLIST_DISABLED
    assert ev.raw == OFF


def test_enforcement_lines_parse_without_the_log_prefix() -> None:
    assert isinstance(parse_line("Turned on the allowlist"), AllowlistEnabled)
    assert isinstance(parse_line("Turned off the allowlist"), AllowlistDisabled)


# -- 2.2 membership announcements --------------------------------
def test_added_carries_the_whole_name_including_spaces() -> None:
    ev = parse_line(ADDED)
    assert isinstance(ev, AllowlistAdded)
    assert ev.name == "Some Player With Spaces"
    assert ev.raw == ADDED


def test_removed_carries_the_whole_name_including_spaces() -> None:
    ev = parse_line(REMOVED)
    assert isinstance(ev, AllowlistRemoved)
    assert ev.name == "Some Player With Spaces"
    assert ev.raw == REMOVED
