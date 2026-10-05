"""Keeps the NetherNet server identity stable across restarts (server-identity
spec; design.md D1-D3, D6).

Without a saved key BDS generates a new identity in memory on every start, so
players must accept the server again after each restart. cobble saves the
*running* identity once (``serveridentity save``) and never replaces a key that
exists. Whether a key exists is read from the file, never from the server.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cobble.console.console import Console, InternalQueryError
from cobble.events.model import Event, EventType
from cobble.logging import get_logger
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import (
    MaintenanceInProgressError,
    NotRunningError,
    Supervisor,
)

log = get_logger("identity.service")

KEY_RELATIVE_PATH = Path("keys") / "server_identity_key.pem"

_SAVE_COMMAND = "serveridentity save"
_SAVE_TIMEOUT = 5.0

_SAVED_RE = re.compile(r"Saved server identity key to\b")
_FAILED_RE = re.compile(r"Failed to save server identity key to\b")


def is_save_reply(line: str) -> bool:
    """True for the two replies ``serveridentity save`` prints. The ``status``
    reply (``A saved server identity key exists at …``) is deliberately not one."""
    return bool(_SAVED_RE.search(line) or _FAILED_RE.search(line))


def is_save_failure(line: str) -> bool:
    return bool(_FAILED_RE.search(line))


class IdentitySaveError(RuntimeError):
    code = "identity_save_failed"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class IdentityState:
    saved: bool
    running: bool

    def to_dict(self) -> dict:
        return {"saved": self.saved, "running": self.running}


class IdentityService:
    def __init__(self, console: Console, supervisor: Supervisor, data_dir: Path) -> None:
        self._console = console
        self._sup = supervisor
        self._key = Path(data_dir) / KEY_RELATIVE_PATH
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    # -- reading ----------------------------------------------------
    def state(self) -> IdentityState:
        """Pure read of the key file and the run state; never raises."""
        try:
            saved = self._key.is_file()
        except OSError:
            saved = False
        return IdentityState(saved=saved, running=self._sup.state is RunState.RUNNING)

    # -- saving -----------------------------------------------------
    async def save_running(self) -> IdentityState:
        """Save the running identity unless a key already exists.

        Raises :class:`MaintenanceInProgressError`, :class:`NotRunningError`, or
        :class:`IdentitySaveError` (a ``Failed …`` reply, a timeout, or a reply
        that was not followed by a file).
        """
        if self._sup.maintenance is not None:
            raise MaintenanceInProgressError(f"a {self._sup.maintenance} operation is in progress")
        if self._sup.state is not RunState.RUNNING:
            raise NotRunningError("the server is not running")

        async with self._lock:
            if self._key.is_file():  # re-check under the lock (design D3)
                return self.state()
            try:
                reply = await self._console.query(
                    _SAVE_COMMAND, is_save_reply, reply_timeout=_SAVE_TIMEOUT
                )
            except InternalQueryError as exc:
                raise IdentitySaveError(str(exc)) from exc
            if is_save_failure(reply):
                raise IdentitySaveError(reply.strip())
            if not self._key.is_file():
                raise IdentitySaveError(
                    f"the server reported the identity saved but {KEY_RELATIVE_PATH} does not exist"
                )
            self._tighten_modes()
            log.info("saved the running server identity key")
            return self.state()

    def _tighten_modes(self) -> None:
        """Leave ``keys/`` no more permissive than 0700 and the PEM than 0600."""
        for path, mode in ((self._key.parent, 0o700), (self._key, 0o600)):
            try:
                current = path.stat().st_mode & 0o777
                if current & ~mode:
                    os.chmod(path, current & mode)
            except OSError:
                log.warning("could not tighten permissions on %s", path, exc_info=True)

    # -- readiness --------------------------------------------------
    def on_event(self, event: Event) -> None:
        """Fast, non-raising. Saves the identity once the server is ready."""
        if event.type is EventType.SERVER_READY:
            task = asyncio.create_task(self._on_ready(), name="cobble-identity-ready")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _on_ready(self) -> None:
        try:
            if self._sup.state is not RunState.RUNNING:
                waiter: Callable | None = getattr(self._sup, "wait_for_state", None)
                if waiter is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(waiter(RunState.RUNNING), timeout=30)
            await self.save_running()
        except Exception:
            log.warning("saving the server identity key at readiness failed", exc_info=True)

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
