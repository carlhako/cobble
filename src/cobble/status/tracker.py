"""Derived, pushed status view (server-status spec).

The tracker owns no lifecycle logic. It observes:

* supervisor run-state transitions — for run state, uptime bracketing, and the
  online-player reset when the server stops;
* the typed event stream — for readiness (uptime start) and player connect/
  disconnect (the online set).

Any change produces a new :class:`StatusSnapshot` pushed to subscribers, so the
interface never polls (server-status spec: "Status changes are pushed").
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from cobble.events.model import (
    Event,
    EventType,
    PlayerConnected,
    PlayerDisconnected,
    PlayerSpawned,
)
from cobble.logging import get_logger
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

log = get_logger("status")

_RESET_STATES = {
    RunState.STOPPED,
    RunState.CRASHED,
    RunState.FAILED,
    RunState.RECOVERY_ABANDONED,
}


@dataclass(frozen=True)
class OnlinePlayer:
    xuid: str
    gamertag: str


@dataclass(frozen=True)
class ShutdownView:
    clean: bool
    at: str


@dataclass(frozen=True)
class StatusSnapshot:
    run_state: RunState
    version: str | None
    uptime_seconds: float | None
    online_players: tuple[OnlinePlayer, ...]
    players_incomplete: bool
    last_shutdown: ShutdownView | None

    def to_dict(self) -> dict:
        return {
            "run_state": self.run_state.value,
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
            "online_players": [
                {"xuid": p.xuid, "gamertag": p.gamertag} for p in self.online_players
            ],
            "players_incomplete": self.players_incomplete,
            "last_shutdown": (
                None
                if self.last_shutdown is None
                else {"clean": self.last_shutdown.clean, "at": self.last_shutdown.at}
            ),
        }


@dataclass(eq=False)
class _Sub:
    queue: asyncio.Queue[StatusSnapshot] = field(default_factory=lambda: asyncio.Queue(maxsize=64))


class StatusTracker:
    def __init__(self, supervisor: Supervisor, *, clock=time.monotonic) -> None:
        self._sup = supervisor
        self._clock = clock
        self._online: dict[str, str] = {}  # xuid -> gamertag
        self._incomplete = False
        self._subs: set[_Sub] = set()

        supervisor.subscribe_state(self._on_state_change)

    # -- event ingestion --------------------------------------
    def on_event(self, event: Event) -> None:
        """Callback for the event bus. Fast and non-raising."""
        if event.type == EventType.PLAYER_CONNECTED and isinstance(event, PlayerConnected):
            self._online[event.xuid] = event.gamertag
            self._emit()
        elif event.type == EventType.PLAYER_SPAWNED and isinstance(event, PlayerSpawned):
            if event.xuid not in self._online:
                # Saw a spawn without the preceding connect — history is partial.
                self._incomplete = True
                self._online[event.xuid] = event.gamertag
                self._emit()
        elif event.type == EventType.PLAYER_DISCONNECTED and isinstance(event, PlayerDisconnected):
            if event.xuid not in self._online:
                self._incomplete = True
            self._online.pop(event.xuid, None)
            self._emit()

    def _on_state_change(self, _frm: RunState, to: RunState) -> None:
        if to in _RESET_STATES:
            self._online.clear()
            # A fresh start from here observes the whole session again.
            if to == RunState.STOPPED:
                self._incomplete = False
        self._emit()

    def mark_observation_incomplete(self) -> None:
        """Called by the runtime when cobble cannot account for the full
        connection history of the running server (e.g. it restored a session it
        did not watch start)."""
        self._incomplete = True
        self._emit()

    # -- snapshot / push ------------------------------------
    def snapshot(self) -> StatusSnapshot:
        rec = self._sup.last_shutdown
        return StatusSnapshot(
            run_state=self._sup.state,
            version=self._sup.installed_version(),
            uptime_seconds=self._sup.uptime_seconds,
            online_players=tuple(
                OnlinePlayer(xuid=x, gamertag=g) for x, g in sorted(self._online.items())
            ),
            players_incomplete=self._incomplete and self._sup.state == RunState.RUNNING,
            last_shutdown=None if rec is None else ShutdownView(clean=rec.clean, at=rec.at),
        )

    def _emit(self) -> None:
        snap = self.snapshot()
        for sub in list(self._subs):
            try:
                sub.queue.put_nowait(snap)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
                sub.queue.put_nowait(snap)

    async def stream(self) -> AsyncIterator[StatusSnapshot]:
        """Current snapshot immediately, then one on every change."""
        sub = _Sub()
        self._subs.add(sub)
        try:
            yield self.snapshot()
            while True:
                yield await sub.queue.get()
        finally:
            self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
