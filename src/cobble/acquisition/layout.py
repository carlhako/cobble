"""On-disk layout for Bedrock installations and cobble's own state (design.md D1/D2).

::

    <bedrock_root>/
        versions/<version>/        pure vendor payload, one directory per version
        current -> versions/<v>     symlink; the active-version indirection
        data/                       stable home for mutable state; BDS's cwd
            server.properties       real (operator config)
            allowlist.json          real
            permissions.json        real
            worlds/                 real (LevelDB; stable path across versions)
            bedrock_server -> ../current/bedrock_server   symlinked vendor payload
            definitions    -> ../current/definitions      ...
    <state_dir>/                    cobble's durable state, captured as a unit

Activating a version replaces the ``current`` symlink and nothing else: the
``data/`` payload symlinks resolve *through* ``current``, so they never need
recreating, and no world or config file is copied or moved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cobble.logging import get_logger
from cobble.settings import Settings

log = get_logger("acquisition.layout")

# Top-level entries in an extracted BDS tree that are mutable operator/world
# state. These live as real files/directories in ``data/`` — never symlinked,
# and relocated there once by the migration (design.md D3). Every *other*
# top-level entry of the active version is vendor payload and is symlinked into
# ``data/`` through ``current``.
#
# Determined by extracting BDS 1.26.45.1 and listing its top level (tasks 1.1):
#   payload dirs : behavior_packs config data definitions development_behavior_packs
#                  development_resource_packs development_skin_packs minecraftpe
#                  premium_cache resource_packs treatments world_templates
#   payload files: Dedicated_Server.txt bedrock_server bedrock_server_how_to.html
#                  libMinecraft.Server.Lib.a packet-statistics.txt
#                  packetlimitconfig.json profanity_filter.wlist release-notes.txt
#   mutable      : worlds/ server.properties allowlist.json permissions.json
MUTABLE_ENTRIES: frozenset[str] = frozenset(
    {"worlds", "server.properties", "allowlist.json", "permissions.json"}
)


class LayoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class Layout:
    bedrock_root: Path
    state_dir: Path
    backup_dir: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> Layout:
        return cls(
            bedrock_root=settings.bedrock_root,
            state_dir=settings.state_dir,
            backup_dir=settings.backup_dir,
        )

    @property
    def versions_dir(self) -> Path:
        return self.bedrock_root / "versions"

    @property
    def current_link(self) -> Path:
        return self.bedrock_root / "current"

    @property
    def data_dir(self) -> Path:
        """Stable mutable-state directory; also BDS's working directory."""
        return self.bedrock_root / "data"

    def version_dir(self, version: str) -> Path:
        return self.versions_dir / version

    # -- bootstrap ------------------------------------------------------
    def ensure_directories(self, *, mode: int = 0o755) -> None:
        """Create the directory layout if absent. Idempotent.

        Ownership follows the process's own uid/gid — the install script runs
        this as the cobble service user, so the directories are owned by it.
        """
        for path in (
            self.bedrock_root,
            self.versions_dir,
            self.data_dir,
            self.data_dir / "worlds",
            self.state_dir,
            self.backup_dir,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=mode)
        log.debug("directory layout ensured under %s and %s", self.bedrock_root, self.state_dir)

    # -- vendor-payload symlinks -------------------------------------
    def payload_entry_names(self) -> list[str]:
        """Top-level entries of the active version that are vendor payload.

        Everything the active version ships except the mutable-state set. An
        active version must be set; raises otherwise.
        """
        version = self.installed_version()
        if version is None:
            raise LayoutError("no active version")
        vdir = self.version_dir(version)
        if not vdir.is_dir():
            raise LayoutError(f"active version directory missing: {vdir}")
        return sorted(p.name for p in vdir.iterdir() if p.name not in MUTABLE_ENTRIES)

    def ensure_payload_symlinks(self) -> None:
        """Create/refresh the ``data/`` symlinks for every vendor-payload entry.

        Each link is ``data/<name> -> ../current/<name>`` so it resolves through
        the active-version indirection. Idempotent: an already-correct link is
        left alone; a stale or wrong-target link is replaced; a real file with a
        payload name (a mutable entry that leaked, or a former layout) is left
        untouched and logged, since only the migration may move real data.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in self.payload_entry_names():
            link = self.data_dir / name
            want = Path("..") / "current" / name
            if link.is_symlink():
                if os.readlink(link) == str(want):
                    continue
                link.unlink()
            elif link.exists():
                log.warning(
                    "data/%s is a real path where a vendor-payload symlink is expected; "
                    "leaving it in place",
                    name,
                )
                continue
            link.symlink_to(want)
        log.debug("vendor-payload symlinks ensured in %s", self.data_dir)

    # -- active-version indirection -----------------------------------
    def installed_version(self) -> str | None:
        """The version the ``current`` symlink points at, or ``None`` if unset."""
        link = self.current_link
        if not link.is_symlink():
            return None
        target = os.readlink(link)
        name = Path(target).name
        return name or None

    def has_installation(self) -> bool:
        version = self.installed_version()
        if version is None:
            return False
        return (self.version_dir(version) / "bedrock_server").is_file()

    def set_active_version(self, version: str) -> None:
        """Point ``current`` at ``version`` by atomically replacing the symlink.

        The switch touches no installation files and leaves every version
        directory and all of ``data/`` intact.
        """
        target_dir = self.version_dir(version)
        if not target_dir.is_dir():
            raise LayoutError(f"version {version!r} is not installed at {target_dir}")

        link = self.current_link
        tmp = link.with_name(f".current.{os.getpid()}.tmp")
        rel_target = Path("versions") / version
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        tmp.symlink_to(rel_target, target_is_directory=True)
        os.replace(tmp, link)  # atomic on the same filesystem
        log.info("active version set to %s", version)

    def bedrock_server_binary(self) -> Path:
        """The real ``bedrock_server`` inside the active version directory."""
        version = self.installed_version()
        if version is None:
            raise LayoutError("no active version")
        return self.version_dir(version) / "bedrock_server"

    @property
    def run_binary(self) -> Path:
        """The ``bedrock_server`` cobble spawns: the ``data/`` symlink, so BDS
        runs with its working directory composed of the payload symlinks."""
        return self.data_dir / "bedrock_server"

    # -- version pruning (server-updates spec, task 6.13) -----------
    def installed_versions(self) -> list[str]:
        """Every version directory present, newest version first."""
        if not self.versions_dir.is_dir():
            return []
        from cobble.acquisition.version import parse_version

        names = [
            p.name
            for p in self.versions_dir.iterdir()
            if p.is_dir() and (p / "bedrock_server").is_file()
        ]
        return sorted(names, key=parse_version, reverse=True)

    def prune_versions(self, keep: set[str]) -> list[str]:
        """Remove version directories not in ``keep`` and older than the oldest
        kept version. The active version and the retained rollback source are
        passed in ``keep`` and never removed. Returns the names removed."""
        from cobble.acquisition.version import parse_version

        if not keep:
            return []
        floor = min(parse_version(v) for v in keep)
        removed: list[str] = []
        import shutil

        for name in self.installed_versions():
            if name in keep:
                continue
            if parse_version(name) >= floor:
                continue  # newer than the rollback source; leave it be
            shutil.rmtree(self.version_dir(name), ignore_errors=True)
            removed.append(name)
        if removed:
            log.info("pruned version directories: %s", ", ".join(removed))
        return removed
