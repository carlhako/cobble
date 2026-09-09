"""Event-bus subscriber that turns observed player events into session rows
(server-players spec; design.md D7).

Subscribes to the bus the same way :class:`~cobble.status.tracker.StatusTracker`
does. The bus contract requires callbacks to be fast and non-raising, and that
is not negotiable here: a database problem must never propagate into the
supervisor or stall the console (D7). Every write failure is logged and dropped,
leaving history incomplete rather than taking the server down.

Session times are stamped from the subscriber's own clock at the moment the
event arrives, not from the log line — events carry no timestamp, and because
cobble spawns BDS itself there is never a backlog to replay (design.md Context).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from cobble.events.model import (
    Event,
    EventType,
    PlayerConnected,
    PlayerDisconnected,
    PlayerSpawned,
)
from cobble.logging import get_logger
from cobble.players.kick import KickIntentRegistry
from cobble.players.storage import END_KICKED, END_OBSERVED, END_RECONSTRUCTED, PlayerStore

log = get_logger("players.recorder")

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SessionRecorder:
    def __init__(
        self,
        store: PlayerStore,
        *,
        clock: Clock = _utcnow,
        kick_intents: KickIntentRegistry | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._kicks = kick_intents

    def on_event(self, event: Event) -> None:
        """Bus callback. Fast and non-raising (D7): any failure is logged and
        swallowed so the supervisor and console are unaffected."""
        try:
            self._dispatch(event)
        except Exception:
            log.exception("recording player history failed; server unaffected, history incomplete")

    def _dispatch(self, event: Event) -> None:
        now = self._clock()
        if event.type == EventType.PLAYER_CONNECTED and isinstance(event, PlayerConnected):
            # A reconnect always starts a new session — never merged with a
            # prior one (D4). If a previous session is somehow still open (a
            # missed disconnect), its end was never observed: close it as
            # reconstructed at its last-known-active time before opening the new
            # one, so no row is left dangling.
            if self._store.has_open_session(event.xuid):
                log.warning(
                    "connect for %s while a session is still open; closing the stale one",
                    event.xuid,
                )
                self._store.reconcile_open_sessions(reason=END_RECONSTRUCTED, xuid=event.xuid)
            self._store.open_session(event.xuid, event.gamertag, now)
        elif event.type == EventType.PLAYER_SPAWNED and isinstance(event, PlayerSpawned):
            self._store.record_spawn(event.xuid, now)
        elif event.type == EventType.PLAYER_DISCONNECTED and isinstance(event, PlayerDisconnected):
            # A departure under a registered kick intent is attributed to the
            # kick (design.md D6). The disconnect line itself is identical to a
            # voluntary leave, so the intent — registered before the command was
            # sent — is the only signal. Its duration is still exact.
            reason = END_OBSERVED
            if self._kicks is not None and self._kicks.satisfy(event.xuid) is not None:
                reason = END_KICKED
            self._store.close_session(event.xuid, now, reason)
