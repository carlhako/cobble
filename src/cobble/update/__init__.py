"""Keeping the installed Bedrock server current (server-updates, section 6).

:mod:`cobble.update.service` holds the state machine: resolve the vendor version,
acquire it while the server keeps running, then a maintenance window of clean
stop, verified pre-update backup, activate, start, readiness + grace check, and
automatic rollback (previous version + pre-update world) on failure. A version
that fails is quarantined so a defective release does not loop nightly.
"""

from __future__ import annotations

from cobble.update.records import FailedVersion, UpdateRecord, UpdateStateStore
from cobble.update.service import (
    UpdateCheck,
    UpdateConflictError,
    UpdateResult,
    UpdateService,
)

__all__ = [
    "FailedVersion",
    "UpdateCheck",
    "UpdateConflictError",
    "UpdateRecord",
    "UpdateResult",
    "UpdateService",
    "UpdateStateStore",
]
