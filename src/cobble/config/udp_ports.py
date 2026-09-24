"""The ``server-udp-ports`` grammar (server-network spec; design.md D2).

Under the NetherNet transport each player connects over its own UDP port, which
BDS picks from the OS's ephemeral range unless ``server-udp-ports`` confines it.
The vendor ``bedrock_server_how_to.html`` ("UDP port configuration for
NetherNet") documents the value as empty, or comma-separated entries, each one of:

* a port, ``19140``;
* an inclusive range, ``19140-19159``;
* a mapping ``[address:]external:internal``, where each side is a port or a range
  and the address is an IPv4 literal or a bracketed IPv6 literal.

This module parses that grammar once, for both the schema validator and the
network view, and derives the views they need: the local ports the server is
confined to, the ports to forward, and whether the value fits the Network
section's from/to form.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

__all__ = [
    "Entry",
    "Form",
    "Range",
    "form",
    "forward_ports",
    "local_ports",
    "parse",
    "port_count",
]


@dataclass(frozen=True)
class Range:
    """An inclusive port range; a single port has ``start == end``."""

    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    def __str__(self) -> str:
        return str(self.start) if self.start == self.end else f"{self.start}-{self.end}"


@dataclass(frozen=True)
class Entry:
    """One comma-separated entry. ``external`` is set only for a mapping."""

    internal: Range
    external: Range | None = None
    address: str | None = None


@dataclass(frozen=True)
class Form:
    """How the Network section can show a value: ``os`` (empty), ``range`` (one
    plain entry, editable as from/to), or ``custom`` (anything else, read-only)."""

    kind: str  # "os" | "range" | "custom"
    start: int | None = None
    end: int | None = None


def _port(text: str) -> int:
    if not text.isdigit():
        raise ValueError(f"{text!r} is not a port number")
    port = int(text)
    if not 1 <= port <= 65535:
        raise ValueError(f"port {port} is outside 1-65535")
    return port


def _range(text: str) -> Range:
    start_text, dash, end_text = text.partition("-")
    start = _port(start_text.strip())
    if not dash:
        return Range(start, start)
    end = _port(end_text.strip())
    if start > end:
        raise ValueError(f"range {text!r} starts after it ends")
    return Range(start, end)


def _address(text: str) -> str:
    if text.startswith("["):
        if not text.endswith("]"):
            raise ValueError(f"address {text!r} has no closing bracket")
        try:
            ipaddress.IPv6Address(text[1:-1])
        except ValueError:
            raise ValueError(f"{text!r} is not an IPv6 address") from None
        return text
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        raise ValueError(f"{text!r} is not an IPv4 address") from None
    return text


def _entry(text: str) -> Entry:
    address: str | None = None
    rest = text
    if text.startswith("["):
        close = text.find("]")
        if close < 0:
            raise ValueError(f"{text!r}: an IPv6 address has no closing bracket")
        address = _address(text[: close + 1])
        rest = text[close + 1 :]
        if not rest.startswith(":"):
            raise ValueError(f"{text!r}: an address must be followed by external:internal")
        rest = rest[1:]
        parts = rest.split(":")
        if len(parts) != 2:
            raise ValueError(f"{text!r}: an address must be followed by external:internal")
    else:
        parts = rest.split(":")
        if len(parts) > 3:
            raise ValueError(f"{text!r}: an IPv6 address must be in brackets, e.g. [::1]")
        if len(parts) == 3:
            address = _address(parts[0])
            parts = parts[1:]

    if len(parts) == 1:
        return Entry(internal=_range(parts[0]))
    external, internal = _range(parts[0]), _range(parts[1])
    if external.size > 1 and internal.size > 1 and external.size != internal.size:
        raise ValueError(
            f"{text!r}: the external range has {external.size} ports "
            f"but the internal range has {internal.size}"
        )
    return Entry(internal=internal, external=external, address=address)


def parse(value: str) -> list[Entry]:
    """Parse a ``server-udp-ports`` value. Empty gives ``[]``.

    Raises :class:`ValueError` naming what is wrong.
    """
    value = value.strip()
    if not value:
        return []
    entries: list[Entry] = []
    for text in value.split(","):
        text = text.strip()
        if not text:
            raise ValueError("an entry between commas is empty")
        entries.append(_entry(text))
    return entries


def _merge(ranges: list[Range]) -> list[Range]:
    merged: list[Range] = []
    for r in sorted(ranges, key=lambda r: r.start):
        if merged and r.start <= merged[-1].end + 1:
            last = merged[-1]
            merged[-1] = Range(last.start, max(last.end, r.end))
        else:
            merged.append(r)
    return merged


def local_ports(entries: list[Entry]) -> list[Range]:
    """The local ports the server is confined to: the internal side of every
    entry, merged into sorted, non-overlapping ranges."""
    return _merge([e.internal for e in entries])


def forward_ports(entries: list[Entry]) -> list[Range]:
    """The ports to forward on the router: the external side of a mapping, or
    the entry itself for a plain port or range. Merged like :func:`local_ports`."""
    return _merge([e.external or e.internal for e in entries])


def port_count(ranges: list[Range]) -> int:
    return sum(r.size for r in ranges)


def form(value: str) -> Form:
    """How the value fits the Network section's range form. An unparseable value
    is ``custom``: it is shown verbatim and never overwritten by the form."""
    try:
        entries = parse(value)
    except ValueError:
        return Form("custom")
    if not entries:
        return Form("os")
    if len(entries) == 1 and entries[0].external is None and entries[0].address is None:
        r = entries[0].internal
        return Form("range", r.start, r.end)
    return Form("custom")
