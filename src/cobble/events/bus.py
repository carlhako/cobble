"""Multi-consumer event dispatch (server-events spec: "Events are observable by
multiple consumers").

Two kinds of subscriber:

* **callback** subscribers — fast, synchronous, in-process consumers such as the
  status tracker. Each call is wrapped so one consumer raising an error does not
  stop others receiving the event or affect the server.
* **queue** subscribers — for slow or remote consumers (an SSE client). Each gets
  its own bounded queue; when it fills, the oldest item is dropped rather than
  blocking the publisher. The stdout pump therefore never blocks on a slow
  consumer ("Output processing does not block the server").
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from cobble.events.model import Event
from cobble.logging import get_logger

log = get_logger("events.bus")

Callback = Callable[[Event], None]


class Subscription:
    """A queue-backed subscription. Async-iterate it to receive events."""

    def __init__(self, bus: EventBus, maxsize: int) -> None:
        self._bus = bus
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def _offer(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
            self._queue.put_nowait(event)

    async def __aiter__(self) -> AsyncIterator[Event]:
        try:
            while True:
                yield await self._queue.get()
        finally:
            self._bus.unsubscribe_queue(self)

    def close(self) -> None:
        self._bus.unsubscribe_queue(self)


class EventBus:
    def __init__(self, *, queue_maxsize: int = 1000) -> None:
        self._callbacks: list[Callback] = []
        self._queues: list[Subscription] = []
        self._queue_maxsize = queue_maxsize

    # -- callback subscribers -------------------------------------
    def subscribe(self, callback: Callback) -> Callable[[], None]:
        self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback) if callback in self._callbacks else None

    # -- queue subscribers --------------------------------------
    def subscribe_queue(self, *, maxsize: int | None = None) -> Subscription:
        sub = Subscription(self, maxsize or self._queue_maxsize)
        self._queues.append(sub)
        return sub

    def unsubscribe_queue(self, sub: Subscription) -> None:
        if sub in self._queues:
            self._queues.remove(sub)

    # -- publishing --------------------------------------------
    def publish(self, event: Event) -> None:
        for cb in list(self._callbacks):
            try:
                cb(event)
            except Exception:
                log.exception("event consumer raised; other consumers unaffected")
        for sub in list(self._queues):
            sub._offer(event)

    @property
    def queue_subscriber_count(self) -> int:
        return len(self._queues)
