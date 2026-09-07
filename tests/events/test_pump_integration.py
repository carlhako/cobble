"""Task 4.1 (integration): the stdout pump keeps draining a rapid producer even
while an event consumer is slow, so the child process is never blocked on output.
"""

from __future__ import annotations

import asyncio

import pytest

from cobble.events.bus import EventBus
from cobble.events.parser import parse_line

pytestmark = pytest.mark.asyncio


async def test_slow_consumer_does_not_stall_a_chatty_server(make_supervisor) -> None:
    bus = EventBus()
    sub = bus.subscribe_queue(maxsize=4)
    sup = make_supervisor(
        line_sink=lambda line: bus.publish(parse_line(line)),
        readiness_timeout=5.0,
    )
    import os

    os.environ["FAKE_BDS_CHATTY"] = "1"
    try:
        await sup.start()
        before = len(sup.console)
        # Consumer is entirely idle here (queue overflows and drops).
        await asyncio.sleep(0.6)
        after = len(sup.console)
    finally:
        os.environ.pop("FAKE_BDS_CHATTY", None)
        await sup.stop()

    # The server kept producing and the pump kept draining into the console
    # buffer despite the stalled consumer.
    assert after > before
    assert sub.dropped > 0
    sub.close()
