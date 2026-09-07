"""Line-recognition primitives for Bedrock server stdout.

Verified against BDS 1.26.x output (design.md). Lines carry a leading
timestamp/level prefix such as ``[2024-11-20 10:15:32:123 INFO] `` which these
patterns tolerate but do not require.

The player forms (design.md — "BDS keeps no player database"):

    Player connected: <gamertag>, xuid: <xuid>
    Player disconnected: <gamertag>, xuid: <xuid>, pfid: <pfid>
    Player Spawned: <gamertag> xuid: <xuid>, pfid: <pfid>

Readiness (design.md D6): the line ``Server started.``.
"""

from __future__ import annotations

import re

# Optional "[ ... ] " log prefix.
_PREFIX = r"(?:\[[^\]]*\]\s*)?"

READINESS_RE = re.compile(_PREFIX + r"Server started\.")

PLAYER_CONNECTED_RE = re.compile(
    _PREFIX + r"Player connected:\s*(?P<gamertag>.+?),\s*xuid:\s*(?P<xuid>\d+)\s*$"
)
PLAYER_DISCONNECTED_RE = re.compile(
    _PREFIX
    + r"Player disconnected:\s*(?P<gamertag>.+?),\s*xuid:\s*(?P<xuid>\d+)"
    + r"(?:,\s*pfid:\s*(?P<pfid>\S+?))?\s*$"
)
PLAYER_SPAWNED_RE = re.compile(
    _PREFIX
    + r"Player Spawned:\s*(?P<gamertag>.+?)\s+xuid:\s*(?P<xuid>\d+)"
    + r"(?:,\s*pfid:\s*(?P<pfid>\S+?))?\s*$"
)


def is_readiness_line(line: str) -> bool:
    return READINESS_RE.search(line) is not None
