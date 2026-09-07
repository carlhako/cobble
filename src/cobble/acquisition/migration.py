"""One-time migration of a pre-separation (M1) installation to the ``data/``
layout (section 4, installation spec, design.md D3).

An M1 installation keeps its world and operator config inside
``versions/<current>/``. This moves them into ``data/`` after capturing a
verified backup, lays out the vendor-payload symlinks, and records completion so
it never runs again.

State is a marker file ``state_dir/layout_migration.json`` whose ``status`` is:

* ``migrating`` — written *before* the first file moves, so an interrupted run is
  always recognisable as a resume rather than mistaken for a fresh install;
* ``migrated``  — the relocation finished;
* ``fresh``     — this host was bootstrapped straight into the ``data/`` layout
  and never had an earlier one.

Moves are per-file ``rename`` calls, so an interruption leaves every file at
exactly one of its two paths and a resume simply finishes the remainder.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cobble.acquisition.layout import Layout
from cobble.backup.service import BackupService
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

log = get_logger("acquisition.migration")

_CONFIG_FILES = ("server.properties", "allowlist.json", "permissions.json")
_DONE = {"migrated", "fresh"}


@dataclass(frozen=True)
class MigrationOutcome:
    migrated: bool
    reason: str


class MigrationError(RuntimeError):
    pass


def _merge_move(src: Path, dst: Path) -> None:
    """Move every child of ``src`` into ``dst`` (skipping any already there),
    then remove ``src`` if it ends up empty."""
    dst.mkdir(parents=True, exist_ok=True)
    for child in list(src.iterdir()):
        target = dst / child.name
        if target.exists():
            continue
        os.replace(child, target)
    with contextlib.suppress(OSError):
        src.rmdir()


class LayoutMigration:
    def __init__(
        self,
        settings: Settings,
        layout: Layout,
        supervisor: Supervisor,
        backup: BackupService,
    ) -> None:
        self._settings = settings
        self._layout = layout
        self._sup = supervisor
        self._backup = backup

    @property
    def _marker(self) -> Path:
        return self._layout.state_dir / "layout_migration.json"

    def _status(self) -> str | None:
        try:
            return str(json.loads(self._marker.read_text()).get("status"))
        except (OSError, ValueError):
            return None

    def _write_marker(self, status: str) -> None:
        self._marker.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._marker.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"status": status, "at": datetime.now(UTC).isoformat(), "format": "data-separation"}
            )
        )
        tmp.replace(self._marker)

    # -- detection (task 4.1) ------------------------------------
    def _world_in_version_dir(self) -> Path | None:
        version = self._layout.installed_version()
        if version is None:
            return None
        world = self._layout.version_dir(version) / "worlds"
        return world if world.is_dir() else None

    def needs_migration(self) -> bool:
        """True for an M1-shaped installation that has not been migrated: a real
        ``worlds/`` directory inside the active version directory, and no
        completed marker."""
        status = self._status()
        if status in _DONE:
            return False
        if status == "migrating":
            return True
        return self._world_in_version_dir() is not None

    # -- execution (tasks 4.2-4.5) --------------------------------
    async def run(self) -> MigrationOutcome:
        """Perform, resume, or skip the migration. Returns an outcome; raises
        :class:`MigrationError` only if the server is not stopped."""
        status = self._status()
        if status in _DONE:
            return MigrationOutcome(False, "installation already uses the separated layout")

        version = self._layout.installed_version()
        if version is None:
            return MigrationOutcome(False, "no installation present; nothing to migrate")
        version_dir = self._layout.version_dir(version)

        resuming = status == "migrating"
        if not resuming and self._world_in_version_dir() is None:
            self._write_marker("fresh")
            return MigrationOutcome(False, "no earlier layout to migrate")

        if self._sup.state is not RunState.STOPPED:
            raise MigrationError(
                f"migration requires the server stopped, but it is {self._sup.state.value}"
            )

        if not resuming:
            log.info("pre-separation layout detected for %s; capturing a backup first", version)
            outcome = await self._backup.capture_pre_migration(version_dir)
            if not outcome.ok:
                return MigrationOutcome(
                    False, f"aborted before moving anything: backup failed: {outcome.error}"
                )
            # Past this point a partial run must be recognised as a resume.
            self._write_marker("migrating")
        else:
            log.warning("resuming an interrupted migration for %s", version)

        self._layout.ensure_directories()
        world_src = version_dir / "worlds"
        if world_src.is_dir():
            _merge_move(world_src, self._layout.data_dir / "worlds")
        for name in _CONFIG_FILES:
            src = version_dir / name
            if not src.is_file():
                continue
            dest = self._layout.data_dir / name
            # First pass: the M1 operator's file is authoritative and replaces
            # anything the bootstrap seeded. Resume: keep what is already there.
            if resuming and dest.exists():
                src.unlink()
            else:
                os.replace(src, dest)

        self._layout.ensure_payload_symlinks()
        self._write_marker("migrated")
        log.info("migration complete: world and config now under %s", self._layout.data_dir)
        return MigrationOutcome(True, "relocated world and config to the data/ layout")
