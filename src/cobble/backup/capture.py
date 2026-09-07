"""Capturing and verifying a backup archive (tasks 3.2, 3.5, 3.6).

Pure filesystem work, no server or event-loop involvement — the caller
(:mod:`cobble.backup.service`) owns stopping the server and runs this in a
thread.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from cobble.acquisition.layout import Layout
from cobble.backup.artifact import (
    CONTENT_DATA,
    CONTENT_STATE,
    CONTENTS,
    MANIFEST_FORMAT,
    PARTIAL_SUFFIX,
    BackupError,
    Manifest,
    archive_name,
    sidecar_for,
)
from cobble.logging import get_logger

log = get_logger("backup.capture")

# Microsecond precision so two captures in the same second (e.g. a pre-restore
# safety capture immediately followed by the restore) never collide.
_STAMP_FMT = "%Y%m%dT%H%M%S.%fZ"


class _HashingWriter:
    """A write-only file wrapper that streams every byte through a hash."""

    def __init__(self, raw: BinaryIO, hasher) -> None:
        self._raw = raw
        self._hash = hasher

    def write(self, data: bytes) -> int:
        self._hash.update(data)
        return self._raw.write(data)

    def flush(self) -> None:
        self._raw.flush()


def _portable(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
    """Strip ownership so a backup restores without matching uids/gids."""
    tarinfo.uid = tarinfo.gid = 0
    tarinfo.uname = tarinfo.gname = ""
    return tarinfo


def capture_archive(
    layout: Layout,
    dest_dir: Path,
    *,
    sources: dict[str, Path] | None = None,
    bedrock_version: str | None,
    shutdown_clean: bool | None,
    now: datetime,
) -> Manifest:
    """Capture ``data/`` and cobble's ``state_dir/`` into a new archive under
    ``dest_dir`` and return its manifest.

    ``sources`` maps an archive member name to a real path; the default captures
    ``data/`` and ``cobble-state/`` whole. The migration (section 4) passes M1
    paths mapped to the same ``data/…`` member layout so a pre-migration backup
    is an ordinary restorable backup.

    Written to ``<name>.partial`` first, then renamed; the sidecar is written
    last. An interrupted call leaves at most a ``.partial`` and never a
    sidecar, so :class:`~cobble.backup.store.BackupStore` never offers it
    (tasks 3.2, 3.5). ``OSError`` (destination absent, full, read-only)
    propagates for the caller to record as an unhealthy condition (task 3.9).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime(_STAMP_FMT)
    base = archive_name(stamp)
    archive = dest_dir / base
    partial = dest_dir / (base.removesuffix(".tar.gz") + PARTIAL_SUFFIX)
    sidecar = sidecar_for(archive)
    partial.unlink(missing_ok=True)

    if sources is None:
        sources = {CONTENT_DATA: layout.data_dir, CONTENT_STATE: layout.state_dir}
    embedded = {
        "format": MANIFEST_FORMAT,
        "captured_at": now.isoformat(),
        "bedrock_version": bedrock_version,
        "shutdown_clean": shutdown_clean,
        "contents": list(CONTENTS),
    }
    hasher = hashlib.sha256()
    try:
        with open(partial, "wb") as raw:
            writer = _HashingWriter(raw, hasher)
            with tarfile.open(fileobj=writer, mode="w:gz") as tar:
                for name, src in sources.items():
                    if src.is_dir():
                        # Symlinks (the data/ vendor payload links) are stored
                        # as symlinks, not dereferenced.
                        tar.add(src, arcname=name, recursive=True, filter=_portable)
                    elif src.is_file():
                        tar.add(src, arcname=name, filter=_portable)
                    else:
                        log.warning("backup source %s (%s) is missing; skipped", name, src)
                meta = json.dumps(embedded, indent=2).encode()
                ti = tarfile.TarInfo("manifest.json")
                ti.size = len(meta)
                ti.mtime = int(now.timestamp())
                tar.addfile(ti, io.BytesIO(meta))
            raw.flush()
            os.fsync(raw.fileno())

        size = partial.stat().st_size
        manifest = Manifest(
            captured_at=now.isoformat(),
            bedrock_version=bedrock_version,
            shutdown_clean=shutdown_clean,
            archive=base,
            sha256=hasher.hexdigest(),
            size_bytes=size,
            contents=CONTENTS,
        )
        os.replace(partial, archive)
        manifest.write_atomic(sidecar)  # completion marker, written last
        log.info("captured backup %s (%.1f MB)", base, size / 1_000_000)
        return manifest
    except BaseException:
        partial.unlink(missing_ok=True)
        # A renamed archive with no sidecar is an interrupted capture: remove it
        # so nothing dangling is left for the store to reason about.
        if archive.exists() and not sidecar.exists():
            archive.unlink(missing_ok=True)
        raise


def verify_archive(archive: Path, manifest: Manifest) -> None:
    """Check a completed archive against its manifest. Raises
    :class:`BackupError` on a truncated, corrupt, or mismatched archive
    (task 3.6)."""
    try:
        actual_size = archive.stat().st_size
    except OSError as exc:
        raise BackupError(f"archive {archive.name} is unreadable: {exc}") from exc
    if actual_size != manifest.size_bytes:
        raise BackupError(
            f"archive {archive.name} size {actual_size} != manifest {manifest.size_bytes}"
        )

    hasher = hashlib.sha256()
    try:
        with open(archive, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                hasher.update(chunk)
    except OSError as exc:
        raise BackupError(f"archive {archive.name} could not be read: {exc}") from exc
    if hasher.hexdigest() != manifest.sha256:
        raise BackupError(f"archive {archive.name} checksum does not match its manifest")

    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            names = tar.getnames()  # forces a full read; raises on truncation
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise BackupError(f"archive {archive.name} is not a readable tar: {exc}") from exc
    if "manifest.json" not in names:
        raise BackupError(f"archive {archive.name} has no embedded manifest.json")
    for content in manifest.contents:
        if not any(n == content or n.startswith(content + "/") for n in names):
            raise BackupError(f"archive {archive.name} is missing '{content}' contents")
