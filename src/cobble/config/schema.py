"""The static schema of recognised ``server.properties`` keys (design.md D2).

Cobble carries its own table of the properties it understands — key, type,
documented default, valid range or member set, and a short description. The
schema is what turns a text field into a checkbox, a bounded number, or a
dropdown, and what lets cobble explain a setting.

The schema is deliberately *not* authoritative over the file. A key present in
the file but absent from this table (a property a newer BDS added, an
operator-added key) is still read, still reported, and still editable as text
(:func:`lookup` returns ``None`` for it). The schema improves the experience for
keys cobble knows and never gates the ones it does not.

The type set is bool / int / float / enum / string. A key cobble cannot type
precisely (a value that is sometimes a keyword and sometimes a number, an enum
whose full member set is uncertain) is modelled as ``string`` — still carrying a
default and description, never rejecting a value.

The table is maintained against the ``server.properties`` a current BDS ships and
is checked against a live vendor file (``tests/config/test_schema.py``). An entry
for a key a newer BDS renamed or dropped is removed when noticed; the old key, if
still in someone's file, survives as an unrecognised text row.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "SCHEMA",
    "PropertySchema",
    "PropertyType",
    "ValidationIssue",
    "lookup",
    "validate",
]


class PropertyType(StrEnum):
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    ENUM = "enum"
    STRING = "string"


@dataclass(frozen=True)
class PropertySchema:
    key: str
    type: PropertyType
    default: str
    description: str
    members: tuple[str, ...] | None = None  # ENUM only
    minimum: float | None = None  # INT / FLOAT only, inclusive
    maximum: float | None = None  # INT / FLOAT only, inclusive

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "type": self.type.value,
            "default": self.default,
            "description": self.description,
            "members": list(self.members) if self.members is not None else None,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True)
class ValidationIssue:
    key: str
    severity: str  # "error" (rejects the write) | "warning" (persisted, surfaced)
    message: str

    def to_dict(self) -> dict:
        return {"key": self.key, "severity": self.severity, "message": self.message}


def _b(key: str, default: str, description: str) -> PropertySchema:
    return PropertySchema(key, PropertyType.BOOL, default, description)


def _s(key: str, default: str, description: str) -> PropertySchema:
    return PropertySchema(key, PropertyType.STRING, default, description)


def _e(key: str, default: str, members: tuple[str, ...], description: str) -> PropertySchema:
    return PropertySchema(key, PropertyType.ENUM, default, description, members=members)


def _i(
    key: str,
    default: str,
    description: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> PropertySchema:
    return PropertySchema(
        key, PropertyType.INT, default, description, minimum=minimum, maximum=maximum
    )


def _f(
    key: str,
    default: str,
    description: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> PropertySchema:
    return PropertySchema(
        key, PropertyType.FLOAT, default, description, minimum=minimum, maximum=maximum
    )


# The keys BDS ships in a freshly extracted ``server.properties``. Ordered to
# match the vendor file for readability of a diff against it.
_ENTRIES: tuple[PropertySchema, ...] = (
    _s("server-name", "Dedicated Server", "Name shown in the in-game server list."),
    _e(
        "gamemode",
        "survival",
        ("survival", "creative", "adventure"),
        "Default game mode for players joining for the first time.",
    ),
    _b(
        "force-gamemode",
        "false",
        "Force every player to the server game mode on join, overriding their own.",
    ),
    _e(
        "difficulty",
        "easy",
        ("peaceful", "easy", "normal", "hard"),
        "World difficulty.",
    ),
    _b("allow-cheats", "false", "Allow cheat commands (/gamemode, /give, …) in this world."),
    _i("max-players", "10", "Maximum number of players that can be connected at once.", minimum=1),
    _b(
        "online-mode",
        "true",
        "Require players to be authenticated with Xbox Live. Disable only on a trusted LAN.",
    ),
    _b(
        "allow-list",
        "false",
        "Restrict connections to players named in allowlist.json. Cobble ships this off.",
    ),
    _i("server-port", "19132", "UDP port for IPv4 clients.", minimum=1, maximum=65535),
    _i("server-portv6", "19133", "UDP port for IPv6 clients.", minimum=1, maximum=65535),
    _b(
        "enable-lan-visibility",
        "true",
        "Announce the server to the local network so it appears on the LAN tab.",
    ),
    _i(
        "view-distance",
        "32",
        "Maximum render distance in chunks. Higher values increase bandwidth and load.",
        minimum=5,
        maximum=96,
    ),
    _i(
        "tick-distance",
        "4",
        "Distance in chunks around a player kept fully simulated.",
        minimum=4,
        maximum=12,
    ),
    _i(
        "player-idle-timeout",
        "30",
        "Minutes before an idle player is disconnected. 0 disables the timeout.",
        minimum=0,
    ),
    _i(
        "max-threads",
        "8",
        "Maximum worker threads the server may use. 0 lets the server decide.",
        minimum=0,
    ),
    _s("level-name", "Bedrock level", "Directory under worlds/ the server loads as the world."),
    _s("level-seed", "", "Seed for generating a new world. Ignored once a world exists."),
    _e(
        "default-player-permission-level",
        "member",
        ("visitor", "member", "operator"),
        "Permission level assigned to a player joining for the first time.",
    ),
    _b(
        "texturepack-required",
        "false",
        "Require clients to accept the world's resource packs before joining.",
    ),
    _s("transport", "raknet", "Network transport the server listens on (e.g. raknet)."),
    _b("content-log-file-enabled", "false", "Write content errors to a log file."),
    _b(
        "content-log-console-output-enabled",
        "false",
        "Echo content-log messages to the server console as well as the log file.",
    ),
    _s(
        "content-log-level",
        "info",
        "Minimum severity written to the content log (e.g. verbose, info, warning, error).",
    ),
    _i(
        "compression-threshold",
        "1",
        "Minimum packet size in bytes before it is compressed.",
        minimum=0,
        maximum=65535,
    ),
    _e(
        "compression-algorithm",
        "zlib",
        ("zlib", "snappy"),
        "Algorithm used for packet compression.",
    ),
    _b(
        "server-authoritative-movement-strict",
        "false",
        "Reject and correct player movement that fails server-side validation.",
    ),
    _b(
        "server-authoritative-dismount-strict",
        "false",
        "Apply strict server-side validation to dismount actions.",
    ),
    _b(
        "server-authoritative-entity-interactions-strict",
        "false",
        "Apply strict server-side validation to entity interactions.",
    ),
    _f(
        "player-position-acceptance-threshold",
        "0.5",
        "Blocks a client's reported position may diverge from the server's before it is corrected.",
        minimum=0.0,
    ),
    _f(
        "player-movement-action-direction-threshold",
        "0.85",
        "Tolerance (0-1) between a player's facing and an action's direction.",
        minimum=0.0,
        maximum=1.0,
    ),
    _f(
        "server-authoritative-block-breaking-pick-range-scalar",
        "1.5",
        "Multiplier applied to the allowed block-breaking reach under server-authoritative mode.",
        minimum=0.0,
    ),
    _e(
        "chat-restriction",
        "None",
        ("None", "Dropped", "Disabled"),
        "Restrict chat: None allows all, Dropped silently drops, Disabled blocks with a message.",
    ),
    _b(
        "disable-player-interaction",
        "false",
        "Prevent players from seeing or interacting with each other.",
    ),
    _b(
        "client-side-chunk-generation-enabled",
        "true",
        "Let clients render chunks beyond the server's simulation distance.",
    ),
    _b(
        "block-network-ids-are-hashes",
        "true",
        "Send block IDs as stable hashes rather than per-session integers.",
    ),
    _b(
        "disable-persona",
        "false",
        "Disable Character Creator skins, forcing classic skins for all players.",
    ),
    _b(
        "disable-custom-skins",
        "false",
        "Reject player skins that are not built in.",
    ),
    _s(
        "server-build-radius-ratio",
        "Disabled",
        '"Disabled", or a ratio 0.0-1.0 of the simulation distance built around a player.',
    ),
    _b(
        "allow-outbound-script-debugging",
        "false",
        "Allow the script engine to open an outbound connection to a debugger.",
    ),
    _b(
        "allow-inbound-script-debugging",
        "false",
        "Allow an inbound script-debugger connection (requires a debugger attached at startup).",
    ),
    _s(
        "script-debugger-auto-attach",
        "disabled",
        "Script debugger auto-attach behaviour (e.g. disabled, connect).",
    ),
)

SCHEMA: dict[str, PropertySchema] = {entry.key: entry for entry in _ENTRIES}


def lookup(key: str) -> PropertySchema | None:
    """The schema for ``key``, or ``None`` when cobble does not recognise it."""
    return SCHEMA.get(key)


def validate(key: str, value: str) -> ValidationIssue | None:
    """Validate ``value`` for ``key``.

    Returns ``None`` when the value is acceptable or the key is unrecognised, a
    ``severity="error"`` issue when the value cannot be the declared type (the
    caller rejects the whole write), or a ``severity="warning"`` issue when the
    value is the right type but outside cobble's recorded range (the caller
    persists it and surfaces the warning) — design.md D3.
    """
    schema = lookup(key)
    if schema is None:
        return None

    if schema.type is PropertyType.BOOL:
        if value not in ("true", "false"):
            return ValidationIssue(key, "error", "must be 'true' or 'false'")
        return None

    if schema.type is PropertyType.ENUM:
        assert schema.members is not None
        if value not in schema.members:
            allowed = ", ".join(schema.members)
            return ValidationIssue(key, "error", f"must be one of: {allowed}")
        return None

    if schema.type in (PropertyType.INT, PropertyType.FLOAT):
        try:
            number: float = (
                int(value.strip()) if schema.type is PropertyType.INT else float(value.strip())
            )
        except ValueError:
            wanted = "a whole number" if schema.type is PropertyType.INT else "a number"
            return ValidationIssue(key, "error", f"must be {wanted}")
        low, high = schema.minimum, schema.maximum
        if (low is not None and number < low) or (high is not None and number > high):
            return ValidationIssue(
                key,
                "warning",
                f"outside the recommended range {_range_text(low, high)}",
            )
        return None

    return None  # STRING accepts any value


def _range_text(low: float | None, high: float | None) -> str:
    if low is not None and high is not None:
        return f"{low} to {high}"
    if low is not None:
        return f"{low} or more"
    return f"{high} or less"
