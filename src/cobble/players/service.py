"""Lifecycle coordinator for player history (server-players spec; design.md D1).

Ties the storage layer to the running system:

* subscribes the :class:`~cobble.players.recorder.SessionRecorder` to the event
  bus (task 2.5);
* closes open sessions when cobble stops the server (tier 1, ``server_stop``) or
  observes an unexpected exit (tier 2, ``server_exit``) — BDS reports neither;
* refreshes each open session's last-known-active time on a lazy interval while
  the server runs (the tier-3 checkpoint);
* on startup, reconciles sessions a previous run left open, before the recorder
  writes anything new.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime

from cobble.events.bus import EventBus
from cobble.logging import get_logger
from cobble.players.kick import KickIntentRegistry
from cobble.players.recorder import SessionRecorder
from cobble.players.storage import END_SERVER_EXIT, END_SERVER_STOP, PlayerStore
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

log = get_logger("players.service")

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PlayerHistoryService:
    def __init__(
        self,
        store: PlayerStore,
        supervisor: Supervisor,
        bus: EventBus,
        *,
        checkpoint_seconds: float = 300.0,
        clock: Clock = _utcnow,
    ) -> None:
        self._store = store
        self._sup = supervisor
        self._clock = clock
        self._checkpoint_seconds = checkpoint_seconds
        # The kick-intent registry is shared with the access service, which
        # registers an intent before it issues a kick (design.md D6).
        self.kick_intents = KickIntentRegistry()
        self._recorder = SessionRecorder(store, clock=clock, kick_intents=self.kick_intents)
        self._checkpoint_task: asyncio.Task[None] | None = None

        bus.subscribe(self._recorder.on_event)
        supervisor.subscribe_pre_stop(self._on_pre_stop)
        supervisor.subscribe_unexpected_exit(self._on_unexpected_exit)

    @property
    def store(self) -> PlayerStore:
        return self._store

    # -- startup reconciliation (D1 tier 3; tasks 4.2/4.3) -----------
    def reconcile(self) -> None:
        """Close any session a previous run left open, at a time no later than
        its last checkpoint — or the recorded shutdown time if that is later and
        present. Must run before the recorder writes any new event."""
        rec = self._sup.last_shutdown
        shutdown_at = rec.at if rec is not None else None
        try:
            closed = self._store.reconcile_open_sessions(shutdown_at=shutdown_at)
            if closed:
                log.info("closed %d session(s) left open by a previous run", closed)
        except Exception:
            log.exception("startup session reconciliation failed; history may be incomplete")

    # -- tier 1 / tier 2 close-outs -------------------------------
    def _on_pre_stop(self, when: datetime) -> None:
        try:
            closed = self._store.close_all_open(when, END_SERVER_STOP)
            if closed:
                log.info("closed %d open session(s) at server stop", closed)
        except Exception:
            log.exception("closing open sessions at server stop failed; history may be incomplete")

    def _on_unexpected_exit(self, when: datetime) -> None:
        try:
            closed = self._store.close_all_open(when, END_SERVER_EXIT)
            if closed:
                log.info("closed %d open session(s) after an unexpected server exit", closed)
        except Exception:
            log.exception("closing open sessions after an unexpected exit failed")

    # -- tier 3 checkpoint loop (task 4.1) -----------------------
    async def start(self) -> None:
        if self._checkpoint_task is None:
            self._checkpoint_task = asyncio.create_task(
                self._checkpoint_loop(), name="cobble-player-checkpoint"
            )

    async def _checkpoint_loop(self) -> None:
        while True:
            await asyncio.sleep(self._checkpoint_seconds)
            if self._sup.state != RunState.RUNNING:
                continue  # nothing is online; the field must not advance
            try:
                self._store.touch_open_sessions(self._clock())
            except Exception:
                log.exception("player-session checkpoint failed; will retry next interval")

    async def aclose(self) -> None:
        if self._checkpoint_task is not None:
            self._checkpoint_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._checkpoint_task
            self._checkpoint_task = None
        self._store.close()
