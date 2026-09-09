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

# Allowlist enforcement transitions (design.md D5). BDS announces a change to
# enforcement but offers no way to query the current state, so these lines are
# the only source of the live value.
ALLOWLIST_ENABLED_RE = re.compile(_PREFIX + r"Turned on the allowlist\s*$")
ALLOWLIST_DISABLED_RE = re.compile(_PREFIX + r"Turned off the allowlist\s*$")

# Allowlist membership changes. The name can contain spaces, so it is captured
# whole up to the fixed trailing phrase.
ALLOWLIST_ADDED_RE = re.compile(_PREFIX + r"Added (?P<name>.+?) to the allowlist\s*$")
ALLOWLIST_REMOVED_RE = re.compile(_PREFIX + r"Removed (?P<name>.+?) from the allowlist\s*$")


def is_readiness_line(line: str) -> bool:
    return READINESS_RE.search(line) is not None
