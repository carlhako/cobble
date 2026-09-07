"""Persisted update state: the last check, the last outcome, and the set of
versions quarantined after a failed update (tasks 6.10, 6.12).

One JSON file under the state directory, so every record survives a cobble
restart and is retrievable without consulting the host's system logs.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cobble.logging import get_logger

log = get_logger("update.records")

_OUTPUT_TAIL_LIMIT = 20_000  # chars of captured server output retained per failure


@dataclass(frozen=True)
class FailedVersion:
    version: str
    step: str  # the step at which the update failed
    at: str  # ISO 8601 UTC
    output_tail: str  # server output captured during the attempt


@dataclass(frozen=True)
class UpdateRecord:
    status: str  # success | up_to_date | skipped | aborted | rolled_back | terminal
    at: str
    detail: str
    from_version: str | None = None
    to_version: str | None = None
    step: str | None = None
    output_tail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("success", "up_to_date")


@dataclass
class _State:
    failed_versions: dict[str, FailedVersion] = field(default_factory=dict)
    last_result: UpdateRecord | None = None
    last_check_at: str | None = None
    last_available: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


class UpdateStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._state = self._load()

    # -- persistence ---------------------------------------------
    def _load(self) -> _State:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return _State()
        except (OSError, ValueError) as exc:
            log.warning("update state %s unreadable (%s); starting fresh", self._path, exc)
            return _State()
        state = _State()
        try:
            for ver, fv in (raw.get("failed_versions") or {}).items():
                state.failed_versions[str(ver)] = FailedVersion(
                    version=str(ver),
                    step=str(fv.get("step", "unknown")),
                    at=str(fv.get("at", "")),
                    output_tail=str(fv.get("output_tail", "")),
                )
            lr = raw.get("last_result")
            if isinstance(lr, dict):
                state.last_result = UpdateRecord(
                    status=str(lr.get("status", "unknown")),
                    at=str(lr.get("at", "")),
                    detail=str(lr.get("detail", "")),
                    from_version=lr.get("from_version"),
                    to_version=lr.get("to_version"),
                    step=lr.get("step"),
                    output_tail=str(lr.get("output_tail", "")),
                )
            state.last_check_at = raw.get("last_check_at")
            state.last_available = raw.get("last_available")
        except (AttributeError, TypeError) as exc:
            log.warning("update state %s malformed (%s); starting fresh", self._path, exc)
            return _State()
        return state

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "failed_versions": {
                v: {"step": fv.step, "at": fv.at, "output_tail": fv.output_tail}
                for v, fv in self._state.failed_versions.items()
            },
            "last_result": None
            if self._state.last_result is None
            else asdict(self._state.last_result),
            "last_check_at": self._state.last_check_at,
            "last_available": self._state.last_available,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._path)

    # -- reads --------------------------------------------------
    @property
    def last_result(self) -> UpdateRecord | None:
        return self._state.last_result

    @property
    def last_check_at(self) -> str | None:
        return self._state.last_check_at

    @property
    def last_available(self) -> str | None:
        return self._state.last_available

    @property
    def failed_versions(self) -> dict[str, FailedVersion]:
        return dict(self._state.failed_versions)

    def is_failed(self, version: str) -> bool:
        return version in self._state.failed_versions

    def get_failed(self, version: str) -> FailedVersion | None:
        return self._state.failed_versions.get(version)

    # -- writes -------------------------------------------------
    def set_last_check(self, *, available: str | None) -> None:
        self._state.last_check_at = _now()
        self._state.last_available = available
        self._save()

    def set_last_result(self, record: UpdateRecord) -> None:
        self._state.last_result = record
        self._save()

    def add_failed(self, version: str, step: str, output_tail: str) -> FailedVersion:
        fv = FailedVersion(
            version=version, step=step, at=_now(), output_tail=output_tail[-_OUTPUT_TAIL_LIMIT:]
        )
        self._state.failed_versions[version] = fv
        self._save()
        log.warning("quarantined version %s (failed at %s)", version, step)
        return fv

    def clear_failed(self, version: str | None = None) -> list[str]:
        if version is None:
            cleared = list(self._state.failed_versions)
            self._state.failed_versions.clear()
        elif version in self._state.failed_versions:
            del self._state.failed_versions[version]
            cleared = [version]
        else:
            cleared = []
        if cleared:
            self._save()
            log.info("cleared failed-version record(s): %s", ", ".join(cleared))
        return cleared
