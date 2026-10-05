"""The deferred half of a restore: swapping a backup's cobble state into place
at the next cobble start (import-backup-archive design.md D5, D6, D8).

A restore cannot replace ``state_dir`` underneath the running process: services
hold ``cobble.db`` open and cache their stores, and cobble's own shutdown
flushes them — over the restored files. So a completed restore stages the
backup's ``cobble-state/`` as ``<state_dir>/.pending-state/`` with a marker, and
cobble restarts. :func:`apply_pending_state` runs in the new process before the
runtime constructs anything, and moves the staged entries into place, keeping
the destination's instance-local entries.

The swap is idempotent: the marker names every staged entry, each is moved
individually, and a re-run after an interruption finishes what is left.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from cobble.backup.artifact import INSTANCE_LOCAL, PENDING_STATE_DIR, PENDING_STATE_MARKER
from cobble.logging import get_logger

log = get_logger("backup.pending")

_RUNTIME_STATE = "runtime.json"


@dataclass(frozen=True)
class PendingRestore:
    """What the marker recorded, and whether the swap succeeded."""

    label: str
    level_name: str | None
    replaced_capture: str | None
    was_running: bool
    error: str | None = None


def pending_dir(state_dir: Path) -> Path:
    return state_dir / PENDING_STATE_DIR


def marker_path(state_dir: Path) -> Path:
    return state_dir / PENDING_STATE_MARKER


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def stage_state(source: Path, state_dir: Path) -> list[str]:
    """Move an extracted ``cobble-state/`` into the pending slot, dropping
    instance-local entries. Returns the staged entry names. Any earlier staging
    is discarded first."""
    dest = pending_dir(state_dir)
    _remove(dest)
    marker_path(state_dir).unlink(missing_ok=True)
    dest.mkdir(parents=True)
    entries: list[str] = []
    if source.is_dir():
        for child in sorted(source.iterdir()):
            if child.name in INSTANCE_LOCAL:
                continue
            shutil.move(str(child), str(dest / child.name))
            entries.append(child.name)
    return entries


def write_marker(
    state_dir: Path,
    *,
    entries: list[str],
    label: str,
    level_name: str | None,
    replaced_capture: str | None,
    was_running: bool,
) -> None:
    """Write the marker last: without it, a staged directory is never applied."""
    path = marker_path(state_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {
                "entries": entries,
                "label": label,
                "level_name": level_name,
                "replaced_capture": replaced_capture,
                "was_running": was_running,
            }
        )
    )
    tmp.replace(path)


def discard_pending(state_dir: Path) -> None:
    """Remove a staged restore and its marker (a restore that failed after
    staging, or a stray directory with no marker)."""
    marker_path(state_dir).unlink(missing_ok=True)
    _remove(pending_dir(state_dir))


def apply_pending_state(state_dir: Path) -> PendingRestore | None:
    """Swap a staged restore into ``state_dir``. ``None`` when nothing is
    pending. Never raises: a failed swap leaves the marker for the next start
    and is reported in the result's ``error`` (design.md D8)."""
    marker = marker_path(state_dir)
    staged = pending_dir(state_dir)
    if not marker.is_file():
        if staged.exists():
            log.warning("discarding a staged restore with no marker")
            _remove(staged)
        return None
    try:
        data = json.loads(marker.read_text())
        entries = [str(e) for e in data["entries"]]
        result = PendingRestore(
            label=str(data.get("label") or "a backup"),
            level_name=data.get("level_name"),
            replaced_capture=data.get("replaced_capture"),
            was_running=bool(data.get("was_running")),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.error("the staged restore's marker is unreadable: %s; discarding it", exc)
        discard_pending(state_dir)
        return PendingRestore("a backup", None, None, False, error=f"marker unreadable: {exc}")

    try:
        keep = set(entries) | set(INSTANCE_LOCAL)
        for name in entries:
            src = staged / name
            if not (src.exists() or src.is_symlink()):
                continue  # moved by an interrupted earlier run
            _remove(state_dir / name)
            shutil.move(str(src), str(state_dir / name))
        for child in list(state_dir.iterdir()):
            if child.name not in keep:
                _remove(child)
        runtime = state_dir / _RUNTIME_STATE
        tmp = runtime.with_suffix(".tmp")
        tmp.write_text(json.dumps({"desired_running": result.was_running}))
        tmp.replace(runtime)
        _remove(staged)
        marker.unlink()
    except OSError as exc:
        log.error("applying the staged restore failed: %s", exc)
        return PendingRestore(
            result.label,
            result.level_name,
            result.replaced_capture,
            result.was_running,
            error=str(exc),
        )
    log.info("applied the staged restore of %s", result.label)
    return result
