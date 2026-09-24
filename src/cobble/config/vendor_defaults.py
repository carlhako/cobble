"""The ``server.properties`` defaults each installed BDS version ships.

A version directory holds the vendor payload untouched, including the vendor's
own ``server.properties`` (installation spec). That file is the authoritative
record of what that version defaults to. cobble's static schema only mirrors it
and can lag behind.

Two consumers:

- :func:`carry_vendor_defaults` runs on a Bedrock update. A setting the operator
  left at the old version's default follows the new version's default, and a
  setting the operator changed is left alone. Without this, a default the vendor
  flips (``transport`` went ``raknet`` -> ``nethernet`` in 1.26.51.1) stays at
  the old value forever, because ``data/server.properties`` is seeded once and
  never merged.
- :func:`vendor_default` backs the transport notice, which compares the running
  transport with the one the running version ships.
"""

from __future__ import annotations

from dataclasses import dataclass

from cobble.acquisition.layout import Layout
from cobble.config.properties import PropertiesDocument
from cobble.logging import get_logger

log = get_logger("config.vendor_defaults")

__all__ = ["DefaultChange", "carry_vendor_defaults", "vendor_default", "vendor_defaults"]


@dataclass(frozen=True)
class DefaultChange:
    """A setting moved from the old version's default to the new version's."""

    key: str
    old: str
    new: str

    def to_dict(self) -> dict:
        return {"key": self.key, "from": self.old, "to": self.new}


def vendor_defaults(layout: Layout, version: str | None) -> dict[str, str] | None:
    """The settings ``version`` ships, or ``None`` when that version's vendor file
    is not on disk (never installed, or pruned)."""
    if not version:
        return None
    path = layout.version_dir(version) / "server.properties"
    if not path.is_file():
        return None
    try:
        return PropertiesDocument.load(path).effective()
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("could not read the vendor defaults of %s: %s", version, exc)
        return None


def vendor_default(layout: Layout, version: str | None, key: str) -> str | None:
    """One setting's default in ``version``, or ``None`` if unknown."""
    defaults = vendor_defaults(layout, version)
    if defaults is None:
        return None
    value = defaults.get(key)
    return value.strip() if value is not None else None


def carry_vendor_defaults(layout: Layout, previous: str | None, new: str) -> list[DefaultChange]:
    """Move settings still at ``previous``'s default to ``new``'s default.

    Only a key whose operator value equals the old default and whose default
    changed between the versions is touched. A key the operator set to anything
    else is theirs. Nothing is done when either version's vendor file is missing.
    Writes preserve comments and ordering (:class:`PropertiesDocument`).
    """
    old_defaults = vendor_defaults(layout, previous)
    new_defaults = vendor_defaults(layout, new)
    path = layout.data_dir / "server.properties"
    if old_defaults is None or new_defaults is None or not path.is_file():
        return []

    doc = PropertiesDocument.load(path)
    current = doc.effective()
    changes: list[DefaultChange] = []
    for key, old_default in old_defaults.items():
        new_default = new_defaults.get(key)
        if new_default is None or new_default.strip() == old_default.strip():
            continue
        value = current.get(key)
        if value is not None and value.strip() == old_default.strip():
            changes.append(DefaultChange(key, value.strip(), new_default.strip()))

    if changes:
        doc.apply({c.key: c.new for c in changes})
        doc.save(path)
        for c in changes:
            log.info(
                "%s follows the new Bedrock default: %s -> %s (%s -> %s)",
                c.key,
                c.old,
                c.new,
                previous,
                new,
            )
    return changes
