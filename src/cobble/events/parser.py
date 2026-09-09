"""Parse a single Bedrock stdout line into a typed :class:`Event`.

``parse_line`` always returns an event: a recognised line yields its typed event
(carrying the raw line), and anything else yields :class:`RawOutput` so nothing
is ever discarded (server-events spec: "Unrecognised output is never
discarded"). A malformed variant of a known line simply falls through to
``RawOutput`` rather than raising.
"""

from __future__ import annotations

from cobble.events.model import (
    AllowlistAdded,
    AllowlistDisabled,
    AllowlistEnabled,
    AllowlistRemoved,
    Event,
    PlayerConnected,
    PlayerDisconnected,
    PlayerSpawned,
    RawOutput,
    ServerReady,
)
from cobble.events.patterns import (
    ALLOWLIST_ADDED_RE,
    ALLOWLIST_DISABLED_RE,
    ALLOWLIST_ENABLED_RE,
    ALLOWLIST_REMOVED_RE,
    PLAYER_CONNECTED_RE,
    PLAYER_DISCONNECTED_RE,
    PLAYER_SPAWNED_RE,
    READINESS_RE,
)


def parse_line(line: str) -> Event:
    if READINESS_RE.search(line):
        return ServerReady(raw=line)

    if ALLOWLIST_ENABLED_RE.search(line):
        return AllowlistEnabled(raw=line)
    if ALLOWLIST_DISABLED_RE.search(line):
        return AllowlistDisabled(raw=line)

    m = ALLOWLIST_ADDED_RE.search(line)
    if m:
        return AllowlistAdded(raw=line, name=m["name"].strip())

    m = ALLOWLIST_REMOVED_RE.search(line)
    if m:
        return AllowlistRemoved(raw=line, name=m["name"].strip())

    m = PLAYER_CONNECTED_RE.search(line)
    if m:
        return PlayerConnected(raw=line, xuid=m["xuid"], gamertag=m["gamertag"].strip())

    m = PLAYER_DISCONNECTED_RE.search(line)
    if m:
        return PlayerDisconnected(raw=line, xuid=m["xuid"], gamertag=m["gamertag"].strip())

    m = PLAYER_SPAWNED_RE.search(line)
    if m:
        return PlayerSpawned(raw=line, xuid=m["xuid"], gamertag=m["gamertag"].strip())

    return RawOutput(raw=line)
