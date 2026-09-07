"""Comparison of dotted Bedrock version strings (e.g. ``1.26.45.1``)."""

from __future__ import annotations


def parse_version(value: str) -> tuple[int, ...]:
    """``"1.26.45.1"`` -> ``(1, 26, 45, 1)``. Non-numeric or empty components
    are treated as 0 so a malformed string still orders deterministically."""
    parts: list[int] = []
    for chunk in value.strip().split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts) or (0,)


def compare_versions(a: str, b: str) -> int:
    """-1 if ``a`` < ``b``, 0 if equal, 1 if ``a`` > ``b``."""
    pa, pb = parse_version(a), parse_version(b)
    width = max(len(pa), len(pb))
    pa += (0,) * (width - len(pa))
    pb += (0,) * (width - len(pb))
    return (pa > pb) - (pa < pb)


def is_newer(candidate: str, installed: str) -> bool:
    return compare_versions(candidate, installed) > 0
