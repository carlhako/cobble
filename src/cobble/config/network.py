"""The network view: how players reach the server (server-network spec; design.md D5).

Derived entirely from the saved configuration, the transport view and the
``server-udp-ports`` grammar; it stores nothing. It describes a layout for each
transport, so the Network section can re-render when the operator switches the
transport in its draft, and names the one the next start will use.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobble.config import udp_ports
from cobble.config.consistency import resolve_transport
from cobble.config.schema import ValidationIssue

__all__ = ["LAN_DISCOVERY_PORT", "network_view"]

# Observed on 1.26.51.1 (bedrock_server listening on UDP 7551 under NetherNet).
# Not configurable and not in the vendor docs; informational only, never
# forwarded or opened.
LAN_DISCOVERY_PORT = 7551


@dataclass(frozen=True)
class _Field:
    key: str
    protocol: str | None  # "tcp" | "udp" | None (not a port)
    label: str


_LAYOUTS: dict[str, tuple[_Field, ...]] = {
    "nethernet": (
        _Field("server-port", "tcp", "Handshake port"),
        _Field("server-ip", None, "Bind address"),
        _Field("server-udp-ports", "udp", "Player UDP ports"),
    ),
    "raknet": (
        _Field("server-port", "udp", "IPv4 port"),
        _Field("server-portv6", "udp", "IPv6 port"),
    ),
}


def _ranges(ranges: list[udp_ports.Range]) -> list[dict]:
    return [{"start": r.start, "end": r.end} for r in ranges]


def _udp_range(value: str) -> dict:
    shape = udp_ports.form(value)
    if shape.kind == "os":
        return {"form": "os"}
    if shape.kind == "range":
        assert shape.start is not None and shape.end is not None
        return {
            "form": "range",
            "start": shape.start,
            "end": shape.end,
            "size": shape.end - shape.start + 1,
        }
    try:
        local = udp_ports.local_ports(udp_ports.parse(value))
    except ValueError:
        local = []  # a malformed hand edit: shown verbatim, confines nothing we can name
    return {
        "form": "custom",
        "value": value,
        "local": _ranges(local),
        "size": udp_ports.port_count(local),
    }


def _layout(transport: str, values: dict[str, str], present: set[str]) -> dict:
    settings = [
        {
            "key": f.key,
            "value": values.get(f.key, ""),
            "present": f.key in present,
            "protocol": f.protocol,
            "label": f.label,
        }
        for f in _LAYOUTS[transport]
    ]
    port = values.get("server-port", "")
    if transport == "raknet":
        return {
            "settings": settings,
            "udp_range": None,
            "lan_discovery": None,
            "forward": [
                {"protocol": "udp", "ports": port},
                {
                    "protocol": "udp",
                    "ports": values.get("server-portv6", ""),
                    "note": "Only needed for IPv6 players.",
                },
            ],
            "pin_required": False,
        }

    raw = values.get("server-udp-ports", "")
    forward = [{"protocol": "tcp", "ports": port}]
    try:
        forward += [
            {"protocol": "udp", "ports": str(r)}
            for r in udp_ports.forward_ports(udp_ports.parse(raw))
        ]
    except ValueError:
        pass
    udp_range = _udp_range(raw)
    return {
        "settings": settings,
        "udp_range": udp_range,
        "lan_discovery": {"protocol": "udp", "port": LAN_DISCOVERY_PORT},
        "forward": forward,
        "pin_required": udp_range["form"] == "os",
    }


def network_view(
    values: dict[str, str],
    present: set[str],
    transport: dict,
    conflicts: list[ValidationIssue],
) -> dict:
    """Build the view.

    ``values`` holds every recognised setting's value (the default when not
    set) with accumulating keys combined; ``present`` names the keys the file
    assigns; ``transport`` is the transport view's dict.
    """
    return {
        "transport": transport,
        "layout": resolve_transport(transport.get("saved"), transport.get("recommended")),
        "layouts": {name: _layout(name, values, present) for name in _LAYOUTS},
        "conflicts": [c.to_dict() for c in conflicts],
    }
