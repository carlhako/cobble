"""Download and extract a Bedrock server version into the versioned layout.

The archive is streamed to a temporary file, extracted into a temporary
directory alongside the target, and only moved into ``versions/<version>/`` once
extraction has fully succeeded. A truncated or corrupt archive therefore leaves
no partial version directory and never becomes the active version.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx

from cobble.acquisition.layout import Layout
from cobble.acquisition.version_source import ResolvedVersion
from cobble.logging import get_logger
from cobble.settings import Settings

log = get_logger("acquisition.installer")


class InstallError(RuntimeError):
    pass


def _download(url: str, dest: Path, settings: Settings) -> None:
    try:
        with httpx.Client(
            headers={"User-Agent": settings.user_agent},
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
        ) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1 << 16):
                        fh.write(chunk)
    except httpx.HTTPError as exc:
        raise InstallError(f"download failed: {exc}") from exc


def _extract(archive: Path, dest_dir: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise InstallError(f"archive is corrupt (first bad entry: {bad})")
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as exc:
        raise InstallError(f"not a valid zip archive: {exc}") from exc

    binary = dest_dir / "bedrock_server"
    if not binary.is_file():
        raise InstallError("extracted archive does not contain 'bedrock_server'")
    binary.chmod(0o755)


def install_version(resolved: ResolvedVersion, layout: Layout, settings: Settings) -> Path:
    """Install ``resolved`` into ``versions/<version>/`` and return that path.

    If the version is already installed, this is a no-op and returns the
    existing directory. Existing version directories are never modified.
    """
    version_dir = layout.version_dir(resolved.version)
    if (version_dir / "bedrock_server").is_file():
        log.info("version %s already installed", resolved.version)
        return version_dir

    layout.versions_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{resolved.version}.", dir=layout.versions_dir))
    archive = staging / "bedrock-server.zip"
    try:
        log.info("downloading BDS %s", resolved.version)
        _download(resolved.download_url, archive, settings)
        extract_dir = staging / "root"
        extract_dir.mkdir()
        _extract(archive, extract_dir)
        archive.unlink(missing_ok=True)
        # Atomic move into place. If a concurrent install won the race, keep theirs.
        try:
            extract_dir.rename(version_dir)
        except OSError as exc:
            if (version_dir / "bedrock_server").is_file():
                log.info("version %s installed concurrently; keeping it", resolved.version)
            else:
                raise InstallError(f"could not move extracted files into place: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    log.info("installed BDS %s at %s", resolved.version, version_dir)
    return version_dir
