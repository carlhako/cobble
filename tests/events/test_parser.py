"""Tasks 4.2, 4.3, 4.4, 4.5."""

from __future__ import annotations

import pytest

from cobble.events.model import (
    EventType,
    PlayerConnected,
    PlayerDisconnected,
    PlayerSpawned,
    RawOutput,
    ServerReady,
)
from cobble.events.parser import parse_line

# Captured BDS 1.26.x stdout (design.md — the three player forms plus the
# readiness line), with the real leading "[YYYY-MM-DD HH:MM:SS:mmm LEVEL] " prefix.
CAPTURED = {
    "ready": "[2024-11-20 10:15:30:451 INFO] Server started.",
    "connected": "[2024-11-20 10:16:02:113 INFO] Player connected: Steve, xuid: 2535412345678901",
    "spawned": "[2024-11-20 10:16:03:998 INFO] Player Spawned: Steve xuid: 2535412345678901, pfid: c1d2e3f4",  # noqa: E501
    "disconnected": "[2024-11-20 10:42:11:007 INFO] Player disconnected: Steve, xuid: 2535412345678901, pfid: c1d2e3f4",  # noqa: E501
    "noise": "[2024-11-20 10:15:29:000 INFO] Running AutoCompaction...",
}


def test_readiness_line_produces_server_ready() -> None:
    ev = parse_line(CAPTURED["ready"])
    assert isinstance(ev, ServerReady)
    assert ev.type is EventType.SERVER_READY
    assert ev.raw == CAPTURED["ready"]


def test_player_connected_extracts_gamertag_and_xuid() -> None:
    ev = parse_line(CAPTURED["connected"])
    assert isinstance(ev, PlayerConnected)
    assert ev.xuid == "2535412345678901"
    assert ev.gamertag == "Steve"
    assert ev.raw == CAPTURED["connected"]


def test_player_spawned_extracts_gamertag_and_xuid() -> None:
    ev = parse_line(CAPTURED["spawned"])
    assert isinstance(ev, PlayerSpawned)
    assert ev.xuid == "2535412345678901"
    assert ev.gamertag == "Steve"


def test_player_disconnected_extracts_gamertag_and_xuid() -> None:
    ev = parse_line(CAPTURED["disconnected"])
    assert isinstance(ev, PlayerDisconnected)
    assert ev.xuid == "2535412345678901"
    assert ev.gamertag == "Steve"


def test_gamertag_with_spaces_and_unicode() -> None:
    line = "[2024-11-20 10:16:02:113 INFO] Player connected: Ender Dragon ✦, xuid: 999"
    ev = parse_line(line)
    assert isinstance(ev, PlayerConnected)
    assert ev.gamertag == "Ender Dragon ✦"
    assert ev.xuid == "999"


def test_unparsed_line_passes_through_as_raw_output() -> None:
    ev = parse_line(CAPTURED["noise"])
    assert isinstance(ev, RawOutput)
    assert ev.raw == CAPTURED["noise"]


def test_malformed_known_line_does_not_raise_and_is_raw() -> None:
    # 4.5 a known form in a changed format degrades to raw, no error
    mangled = "[INFO] Player connected Steve xuid 12345"  # missing punctuation
    ev = parse_line(mangled)
    assert isinstance(ev, RawOutput)


def test_readiness_not_matched_by_similar_lines() -> None:
    assert isinstance(parse_line("[INFO] Server starting..."), RawOutput)
    assert isinstance(parse_line("[INFO] Starting Server"), RawOutput)


def test_every_event_round_trips_its_source_line() -> None:
    for line in CAPTURED.values():
        assert parse_line(line).raw == line


@pytest.mark.parametrize("prefix", ["", "[INFO] ", "[2024-11-20 10:15:30:451 INFO] "])
def test_prefix_is_tolerated_but_not_required(prefix: str) -> None:
    ev = parse_line(f"{prefix}Server started.")
    assert isinstance(ev, ServerReady)
