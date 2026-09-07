"""Parse a single Bedrock stdout line into a typed :class:`Event`.

``parse_line`` always returns an event: a recognised line yields its typed event
(carrying the raw line), and anything else yields :class:`RawOutput` so nothing
is ever discarded (server-events spec: "Unrecognised output is never
discarded"). A malformed variant of a known line simply falls through to
``RawOutput`` rather than raising.
"""

from __future__ import annotations

from cobble.events.model import (
    Event,
    PlayerConnected,
    PlayerDisconnected,
    PlayerSpawned,
    RawOutput,
    ServerReady,
)
from cobble.events.patterns import (
    PLAYER_CONNECTED_RE,
    PLAYER_DISCONNECTED_RE,
    PLAYER_SPAWNED_RE,
    READINESS_RE,
)


def parse_line(line: str) -> Event:
    if READINESS_RE.search(line):
        return ServerReady(raw=line)

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
