"""Kick-intent registry (server-players spec; design.md D6).

A departure caused by a kick is byte-identical to a voluntary leave in the
server's output, and the disconnect line arrives only a few milliseconds after
the kick acknowledgement — so there is no window in which to decide afterwards.
The intent ("a disconnect for this xuid in the next N seconds is a kick") is
registered *before* the command is sent. The session recorder consults this
registry when it observes a departure; the access service awaits the intent's
event to learn the kick was confirmed.

An intent that no departure satisfies simply expires, so a later voluntary leave
by the same player is not misattributed (task 4.4).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field

Clock = Callable[[], float]


@dataclass
class KickIntent:
    xuid: str
    reason: str
    expires_at: float  # monotonic deadline
    satisfied: asyncio.Event = field(default_factory=asyncio.Event)


class KickIntentRegistry:
    """Not thread-safe; used from the event loop only, like the recorder."""

    def __init__(self, *, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._intents: dict[str, KickIntent] = {}

    def register(self, xuid: str, reason: str, *, ttl: float) -> KickIntent:
        intent = KickIntent(xuid=xuid, reason=reason, expires_at=self._clock() + ttl)
        self._intents[xuid] = intent
        return intent

    def active(self, xuid: str) -> KickIntent | None:
        """The unexpired intent for ``xuid``, or ``None``. Expired intents are
        dropped as a side effect."""
        intent = self._intents.get(xuid)
        if intent is None:
            return None
        if self._clock() >= intent.expires_at:
            del self._intents[xuid]
            return None
        return intent

    def satisfy(self, xuid: str) -> KickIntent | None:
        """Mark the active intent for ``xuid`` satisfied (a departure was
        observed) and return it. The awaiting kick call resolves on its event."""
        intent = self.active(xuid)
        if intent is None:
            return None
        intent.satisfied.set()
        del self._intents[xuid]
        return intent

    def discard(self, xuid: str) -> None:
        self._intents.pop(xuid, None)

    def pending(self) -> list[str]:
        now = self._clock()
        return [x for x, i in self._intents.items() if now < i.expires_at]
