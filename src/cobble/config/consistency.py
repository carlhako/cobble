"""Settings that are each valid but conflict with one another (server-config
spec, "Configuration consistency is reported"; design.md D4).

Pure: an effective settings map goes in, warnings come out. The configuration
service runs it on every read and on any write that touches a key in
:data:`KEYS`, so a conflict shows up whichever page saved it, and a hand edit
shows up on the next read.
"""

from __future__ import annotations

from cobble.config import udp_ports
from cobble.config.schema import SCHEMA, ValidationIssue

__all__ = ["KEYS", "consistency", "resolve_transport"]

# Every key a rule below reads. A write touching any of them re-runs the check.
KEYS = frozenset({"transport", "max-players", "server-udp-ports"})


def resolve_transport(raw: str | None, recommended: str | None) -> str:
    """The transport BDS will use: the saved value, else the version's default,
    else cobble's schema default when the version's vendor file is unknown."""
    return (raw or "").strip() or recommended or SCHEMA["transport"].default


def consistency(
    effective: dict[str, str], recommended_transport: str | None
) -> list[ValidationIssue]:
    """The conflicts in ``effective`` (accumulating keys already combined)."""
    issues: list[ValidationIssue] = []

    # Each NetherNet player holds its own UDP port, so a pinned range smaller
    # than max-players turns players away before the limit is reached.
    transport = resolve_transport(effective.get("transport"), recommended_transport)
    if transport == "nethernet":
        try:
            entries = udp_ports.parse(effective.get("server-udp-ports", ""))
            players = int(effective.get("max-players", SCHEMA["max-players"].default).strip())
        except ValueError:
            entries = []  # malformed values are reported by validation, not here
        ports = udp_ports.port_count(udp_ports.local_ports(entries))
        if entries and ports < players:
            issues.append(
                ValidationIssue(
                    "server-udp-ports",
                    "warning",
                    f"server-udp-ports allows {ports} UDP port{'s' if ports != 1 else ''} but "
                    f"max-players is {players}. Each NetherNet player needs its own port: "
                    f"widen the range to at least {players} ports or lower max-players.",
                )
            )
    return issues
