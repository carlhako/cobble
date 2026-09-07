"""Download and extract a Bedrock server version into the versioned layout.

The archive is streamed to a temporary file, extracted into a temporary
directory alongside the target, and only moved into ``versions/<version>/`` once
extraction has fully succeeded. A truncated or corrupt archive therefore leaves
no partial version directory and never becomes the active version.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

from cobble.acquisition.layout import Layout
from cobble.acquisition.version_source import ResolvedVersion
from cobble.logging import get_logger
from cobble.settings import Settings

log = get_logger("acquisition.installer")

# The Bedrock zip is ~100 MB from a CDN that, on a fresh container, frequently
# starts streaming and then stalls. Restarting from zero on every stall means a
# slow link never finishes, so the download is *resumable*: a stalled transfer
# keeps its partial file and continues with a Range request. Give up only after
# many attempts AND no forward progress.
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=30.0, read=90.0, write=60.0, pool=30.0)
_DOWNLOAD_MAX_ATTEMPTS = 40
_DOWNLOAD_MAX_STALLED = 6  # consecutive attempts with zero bytes gained -> abort
_DOWNLOAD_BACKOFF = 5.0
# A browser-ish agent: some CDN edges throttle or stall unknown agents.
_DOWNLOAD_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 cobble/0.1"
)


class InstallError(RuntimeError):
    pass


def _content_length(client: httpx.Client, url: str) -> int | None:
    try:
        r = client.head(url)
        r.raise_for_status()
        cl = r.headers.get("content-length")
        return int(cl) if cl else None
    except (httpx.HTTPError, ValueError):
        return None


def _download(url: str, dest: Path, settings: Settings) -> None:
    """Download ``url`` to ``dest``, resuming across stalls and transient errors.

    Each attempt requests ``bytes=<have>-`` and appends what it receives. An
    attempt that gains nothing counts as stalled; the download aborts only after
    several consecutive stalls with no forward progress at all.
    """
    del settings  # the download UA is fixed (see _DOWNLOAD_UA)
    headers = {"User-Agent": _DOWNLOAD_UA, "Accept-Encoding": "identity"}
    dest.unlink(missing_ok=True)

    with httpx.Client(headers=headers, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        expected = _content_length(client, url)
        if expected:
            log.info("expected download size: %.1f MB", expected / 1_000_000)

        stalled = 0
        last_exc: Exception | None = None
        for attempt in range(1, _DOWNLOAD_MAX_ATTEMPTS + 1):
            have = dest.stat().st_size if dest.exists() else 0
            if expected and have >= expected:
                break

            clean = False
            try:
                req_headers = {"Range": f"bytes={have}-"} if have else {}
                with client.stream("GET", url, headers=req_headers) as resp:
                    if have and resp.status_code == 200:
                        dest.unlink(missing_ok=True)  # server ignored Range; restart
                        have = 0
                    resp.raise_for_status()
                    with dest.open("ab" if have else "wb") as fh:
                        for chunk in resp.iter_bytes(chunk_size=1 << 16):
                            fh.write(chunk)
                clean = True
            except (httpx.HTTPError, OSError) as exc:
                last_exc = exc

            now = dest.stat().st_size if dest.exists() else 0
            # A clean stream to EOF means the body finished: done unless a
            # Content-Length says otherwise.
            if clean and (not expected or now >= expected):
                break
            if now > have:
                stalled = 0
                last_exc = None
                log.info("download progress: %.1f MB", now / 1_000_000)
                continue

            stalled += 1
            log.warning(
                "download attempt %d gained nothing (%.1f MB so far): %s",
                attempt,
                now / 1_000_000,
                last_exc or "connection closed early",
            )
            if stalled >= _DOWNLOAD_MAX_STALLED:
                raise InstallError(
                    f"download stalled at {now / 1_000_000:.1f} MB of "
                    f"{f'{expected / 1_000_000:.1f} MB' if expected else 'unknown size'} "
                    f"after {stalled} attempts with no progress: {last_exc}"
                )
            time.sleep(min(_DOWNLOAD_BACKOFF * stalled, 30))
        else:
            raise InstallError(
                f"download did not complete after {_DOWNLOAD_MAX_ATTEMPTS} attempts: {last_exc}"
            )

    final = dest.stat().st_size if dest.exists() else 0
    if final == 0:
        raise InstallError("download produced an empty file")
    if expected and final != expected:
        raise InstallError(f"download size mismatch: got {final} bytes, expected {expected}")
    log.info("downloaded %.1f MB", final / 1_000_000)


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
        log.info("downloading BDS %s from %s", resolved.version, resolved.download_url)
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
