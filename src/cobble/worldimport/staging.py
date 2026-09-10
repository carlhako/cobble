"""The single upload staging slot (section 2, design.md D8).

One fixed path under ``<state_dir>/import-staging/`` holds at most one archive.
An upload is written to ``upload.partial`` and renamed to ``upload.zip`` on
completion, so an interrupted transfer is never offered as applicable. A new
upload replaces the slot; an apply or a discard clears it; a sweep at startup
discards anything left from a previous run. The inspection result is cached
beside the archive, keyed to its size and mtime, so repeated reads of a
multi-gigabyte zip do not rescan it (task 2.5).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import BinaryIO

from cobble.logging import get_logger

log = get_logger("worldimport.staging")

_ARCHIVE = "upload.zip"
_PARTIAL = "upload.partial"
_INSPECTION = "inspection.json"


class StagingSlot:
    def __init__(self, root: Path) -> None:
        # ``root`` is ``<state_dir>/import-staging``; created on demand only.
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    @property
    def archive_path(self) -> Path:
        return self._root / _ARCHIVE

    @property
    def partial_path(self) -> Path:
        return self._root / _PARTIAL

    @property
    def _inspection_path(self) -> Path:
        return self._root / _INSPECTION

    def _ensure(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    # -- held archive --------------------------------------------------
    def held(self) -> Path | None:
        """The applicable archive, or ``None``. A stray ``.partial`` is never
        reported (task 2.2)."""
        return self.archive_path if self.archive_path.is_file() else None

    # -- upload ------------------------------------------------------
    def open_partial(self) -> BinaryIO:
        """Open the partial-upload file for writing, truncating any prior one.
        The already-held archive is left untouched until :meth:`commit_partial`."""
        self._ensure()
        self.partial_path.unlink(missing_ok=True)
        return open(self.partial_path, "wb")

    def commit_partial(self) -> Path:
        """Atomically make the completed partial the held archive, replacing any
        previous one and invalidating the cached inspection."""
        if not self.partial_path.is_file():
            raise FileNotFoundError("no completed upload to commit")
        self._inspection_path.unlink(missing_ok=True)
        os.replace(self.partial_path, self.archive_path)
        log.info("import: staged archive %s", self.archive_path)
        return self.archive_path

    def abort_partial(self) -> None:
        self.partial_path.unlink(missing_ok=True)

    # -- lifecycle -------------------------------------------------
    def clear(self) -> None:
        """Discard whatever the slot holds and reclaim the storage — used by
        replace-on-upload, clear-on-apply, and an operator discard (task 2.3)."""
        for p in (self.archive_path, self.partial_path, self._inspection_path):
            p.unlink(missing_ok=True)
        # Any transient extraction staging the service left behind.
        shutil.rmtree(self._root / ".extract", ignore_errors=True)

    def sweep(self) -> None:
        """Startup sweep: nothing from a previous run survives (task 2.4)."""
        if self._root.exists():
            self.clear()
            log.info("import: swept the staging slot on startup")

    # -- inspection cache ---------------------------------------
    def _cache_key(self) -> dict | None:
        try:
            st = self.archive_path.stat()
        except OSError:
            return None
        return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}

    def load_inspection(self) -> dict | None:
        """The cached inspection payload for the currently held archive, or
        ``None`` when there is no cache or it does not match the archive."""
        key = self._cache_key()
        if key is None:
            return None
        try:
            blob = json.loads(self._inspection_path.read_text())
        except (OSError, ValueError):
            return None
        if blob.get("key") != key:
            self._inspection_path.unlink(missing_ok=True)
            return None
        payload = blob.get("payload")
        return payload if isinstance(payload, dict) else None

    def store_inspection(self, payload: dict) -> None:
        key = self._cache_key()
        if key is None:
            return
        self._ensure()
        tmp = self._inspection_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"key": key, "payload": payload}))
        tmp.replace(self._inspection_path)
