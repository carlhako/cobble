"""The typed event vocabulary (server-events spec).

Every event retains the original unmodified source line in ``raw``. XUID is the
player identifier; the gamertag is a display name that is explicitly not treated
as stable (design.md — "BDS keeps no player database").
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import ClassVar


class EventType(enum.StrEnum):
    RAW_OUTPUT = "raw_output"
    SERVER_READY = "server_ready"
    PLAYER_CONNECTED = "player_connected"
    PLAYER_DISCONNECTED = "player_disconnected"
    PLAYER_SPAWNED = "player_spawned"
    ALLOWLIST_ENABLED = "allowlist_enabled"
    ALLOWLIST_DISABLED = "allowlist_disabled"
    ALLOWLIST_ADDED = "allowlist_added"
    ALLOWLIST_REMOVED = "allowlist_removed"


@dataclass(frozen=True, slots=True)
class Event:
    raw: str
    type: ClassVar[EventType]


@dataclass(frozen=True, slots=True)
class RawOutput(Event):
    """A line cobble could not classify. Still delivered to the console."""

    type: ClassVar[EventType] = EventType.RAW_OUTPUT


@dataclass(frozen=True, slots=True)
class ServerReady(Event):
    type: ClassVar[EventType] = EventType.SERVER_READY


@dataclass(frozen=True, slots=True)
class PlayerConnected(Event):
    type: ClassVar[EventType] = EventType.PLAYER_CONNECTED
    xuid: str = ""
    gamertag: str = ""


@dataclass(frozen=True, slots=True)
class PlayerDisconnected(Event):
    type: ClassVar[EventType] = EventType.PLAYER_DISCONNECTED
    xuid: str = ""
    gamertag: str = ""


@dataclass(frozen=True, slots=True)
class PlayerSpawned(Event):
    type: ClassVar[EventType] = EventType.PLAYER_SPAWNED
    xuid: str = ""
    gamertag: str = ""


@dataclass(frozen=True, slots=True)
class AllowlistEnabled(Event):
    """The server announced ``Turned on the allowlist`` (design.md D5)."""

    type: ClassVar[EventType] = EventType.ALLOWLIST_ENABLED


@dataclass(frozen=True, slots=True)
class AllowlistDisabled(Event):
    """The server announced ``Turned off the allowlist``."""

    type: ClassVar[EventType] = EventType.ALLOWLIST_DISABLED


@dataclass(frozen=True, slots=True)
class AllowlistAdded(Event):
    """The server announced a player was added to the allowlist."""

    type: ClassVar[EventType] = EventType.ALLOWLIST_ADDED
    name: str = ""


@dataclass(frozen=True, slots=True)
class AllowlistRemoved(Event):
    """The server announced a player was removed from the allowlist."""

    type: ClassVar[EventType] = EventType.ALLOWLIST_REMOVED
    name: str = ""


PLAYER_EVENT_TYPES = (
    EventType.PLAYER_CONNECTED,
    EventType.PLAYER_DISCONNECTED,
    EventType.PLAYER_SPAWNED,
)
