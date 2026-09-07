"""On-disk layout for Bedrock installations and cobble's own state (design.md D5).

::

    <bedrock_root>/
        versions/<version>/        extracted BDS, one directory per version
        current -> versions/<v>     symlink; the active-version indirection
    <state_dir>/                    cobble's durable state, captured as a unit

The ``current`` symlink is the only thing that changes when the active version
changes: no installation files are copied or moved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cobble.logging import get_logger
from cobble.settings import Settings

log = get_logger("acquisition.layout")


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

    def version_dir(self, version: str) -> Path:
        return self.versions_dir / version

    # -- bootstrap ------------------------------------------------------
    def ensure_directories(self, *, mode: int = 0o755) -> None:
        """Create the directory layout if absent. Idempotent.

        Ownership follows the process's own uid/gid — the install script runs
        this as the cobble service user, so the directories are owned by it.
        """
        for path in (self.bedrock_root, self.versions_dir, self.state_dir, self.backup_dir):
            path.mkdir(parents=True, exist_ok=True, mode=mode)
        log.debug("directory layout ensured under %s and %s", self.bedrock_root, self.state_dir)

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
        directory intact.
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
        version = self.installed_version()
        if version is None:
            raise LayoutError("no active version")
        return self.version_dir(version) / "bedrock_server"
