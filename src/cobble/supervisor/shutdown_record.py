"""Persisted record of the most recent shutdown's cleanliness (design.md D7,
server-lifecycle spec: "Record survives cobble restart").

A shutdown that required SIGKILL is recorded as unclean so later mechanisms can
refuse to trust the resulting state.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from cobble.logging import get_logger

log = get_logger("supervisor.shutdown_record")


@dataclass(frozen=True)
class ShutdownRecord:
    clean: bool
    at: str  # ISO 8601 UTC
    reason: str  # "stop", "sigkill", "restart", "cobble_terminate"

    @classmethod
    def now(cls, *, clean: bool, reason: str) -> ShutdownRecord:
        return cls(clean=clean, at=datetime.now(UTC).isoformat(), reason=reason)


def load_last_shutdown(path: Path) -> ShutdownRecord | None:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("could not read shutdown record %s: %s", path, exc)
        return None
    try:
        return ShutdownRecord(
            clean=bool(data["clean"]), at=str(data["at"]), reason=str(data["reason"])
        )
    except (KeyError, TypeError):
        log.warning("shutdown record %s is malformed", path)
        return None


def store_last_shutdown(path: Path, record: ShutdownRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(record)))
    tmp.replace(path)
    log.info(
        "recorded %s shutdown at %s (%s)",
        "clean" if record.clean else "UNCLEAN",
        record.at,
        record.reason,
    )
