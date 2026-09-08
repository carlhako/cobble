"""Operator-editable configuration of the Bedrock server (server-config spec, M3).

* :mod:`cobble.config.properties` — the line-oriented ``server.properties``
  document: parse, effective-value view, comment-preserving in-place writes, and
  atomic persistence.
* :mod:`cobble.config.schema` — the static table of recognised properties
  (type, default, range/members, description) and value validation.
* :mod:`cobble.config.service` — the configuration service: reads, all-or-nothing
  writes, the worlds backing ``level-name``, and the pending-versus-live
  comparison against the snapshot the supervisor takes at spawn.
"""

from __future__ import annotations

from cobble.config.properties import PropertiesDocument
from cobble.config.schema import (
    PropertySchema,
    PropertyType,
    ValidationIssue,
    lookup,
    validate,
)
from cobble.config.service import (
    ConfigService,
    ConfigWriteResult,
    PendingChange,
    Setting,
    WorldInfo,
)

__all__ = [
    "ConfigService",
    "ConfigWriteResult",
    "PendingChange",
    "PropertiesDocument",
    "PropertySchema",
    "PropertyType",
    "Setting",
    "ValidationIssue",
    "WorldInfo",
    "lookup",
    "validate",
]
