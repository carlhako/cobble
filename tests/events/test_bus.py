"""Tasks 4.1, 4.6."""

from __future__ import annotations

import asyncio

import pytest

from cobble.events.bus import EventBus
from cobble.events.model import RawOutput, ServerReady

pytestmark = pytest.mark.asyncio


async def test_multiple_callback_consumers_all_receive_events() -> None:
    bus = EventBus()
    a: list[str] = []
    b: list[str] = []
    bus.subscribe(lambda e: a.append(e.raw))
    bus.subscribe(lambda e: b.append(e.raw))
    bus.publish(RawOutput(raw="one"))
    bus.publish(ServerReady(raw="two"))
    assert a == ["one", "two"]
    assert b == ["one", "two"]


async def test_one_consumer_raising_does_not_stop_others() -> None:
    # 4.6 one consumer raising an error does not prevent others receiving it
    bus = EventBus()
    got: list[str] = []

    def broken(_e):
        raise RuntimeError("boom")

    bus.subscribe(broken)
    bus.subscribe(lambda e: got.append(e.raw))
    bus.publish(RawOutput(raw="still delivered"))
    assert got == ["still delivered"]


async def test_slow_queue_consumer_does_not_block_publisher() -> None:
    # 4.1 a slow consumer does not stall a producer emitting rapidly
    bus = EventBus()
    sub = bus.subscribe_queue(maxsize=8)

    # Publish far more than the queue can hold, synchronously and fast.
    for i in range(1000):
        bus.publish(RawOutput(raw=str(i)))

    # Publisher never blocked; the subscription dropped the overflow and kept
    # the most recent items.
    assert sub.dropped >= 900
    received: list[str] = []
    for _ in range(8):
        received.append((await asyncio.wait_for(sub.__aiter__().__anext__(), 1)).raw)
    assert received[-1] == "999"
    sub.close()


async def test_queue_consumer_receives_live_events() -> None:
    bus = EventBus()
    sub = bus.subscribe_queue()
    it = sub.__aiter__()
    bus.publish(ServerReady(raw="ready"))
    ev = await asyncio.wait_for(it.__anext__(), 1)
    assert ev.raw == "ready"
    sub.close()
    assert bus.queue_subscriber_count == 0
