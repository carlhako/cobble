"""Tasks 5.1-5.5."""

from __future__ import annotations

import asyncio
import os

import pytest

from cobble.console.buffer import ConsoleBuffer, LineKind
from cobble.console.console import Console
from cobble.supervisor.supervisor import NotRunningError, Supervisor


# -- 5.1 buffer ---------------------------------------------------------
def test_buffer_is_bounded_and_keeps_most_recent() -> None:
    buf = ConsoleBuffer(maxlen=100)
    for i in range(1000):
        buf.add_output(f"line {i}")
    assert len(buf) == 100
    texts = [line.text for line in buf.snapshot()]
    assert texts[0] == "line 900"
    assert texts[-1] == "line 999"


def test_buffer_listener_fires_for_every_kind() -> None:
    buf = ConsoleBuffer(maxlen=10)
    seen: list[tuple[LineKind, str]] = []
    buf.add_listener(lambda ln: seen.append((ln.kind, ln.text)))
    buf.add_output("o")
    buf.add_command("c")
    buf.add_marker("m")
    assert seen == [
        (LineKind.OUTPUT, "o"),
        (LineKind.COMMAND, "c"),
        (LineKind.MARKER, "m"),
    ]


async def test_history_survives_restart_with_restart_distinguishable(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    Console(sup)
    await sup.start()
    pre_restart = sup.console.last_seq()
    await sup.restart()
    await sup.stop()
    kinds = [ln.kind for ln in sup.console.snapshot()]
    texts = [ln.text for ln in sup.console.snapshot()]
    assert LineKind.MARKER in kinds  # the restart boundary is visible
    assert any("Starting Server" in t for t in texts[:5])  # pre-restart output kept
    assert sup.console.last_seq() > pre_restart


# -- 5.2 stream -------------------------------------------------------
async def test_two_clients_receive_identical_output(make_supervisor) -> None:
    os.environ["FAKE_BDS_CHATTY"] = "1"  # idle server emits a steady stream
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    console = Console(sup)
    try:
        await sup.start()

        async def collect(n: int) -> list[str]:
            out: list[str] = []
            async for line in console.stream():
                out.append(f"{line.seq}:{line.text}")
                if len(out) >= n:
                    return out
            return out

        a, b = await asyncio.gather(collect(8), collect(8))
    finally:
        os.environ.pop("FAKE_BDS_CHATTY", None)
        await sup.stop()
    assert a == b  # same seq + text for both clients


async def test_client_connecting_to_stopped_server_gets_output_once_started(
    make_supervisor,
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0, readiness_timeout=5.0)
    console = Console(sup)
    assert sup.state.value == "stopped"

    received: list[str] = []

    async def reader() -> None:
        async for line in console.stream():
            received.append(line.text)
            if any("Server started." in r for r in received):
                return

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.1)  # client is connected while server is stopped
    await sup.start()
    await asyncio.wait_for(task, timeout=5)
    await sup.stop()
    assert any("Server started." in r for r in received)


# -- 5.3 / 5.4 commands --------------------------------------------
async def test_concurrent_commands_delivered_intact_without_interleaving(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    console = Console(sup)
    await sup.start()

    a = "aaaaaaaaaaaaaaaaaaaa"
    b = "bbbbbbbbbbbbbbbbbbbb"
    await asyncio.gather(
        *[console.submit_command(a) for _ in range(20)],
        *[console.submit_command(b) for _ in range(20)],
    )
    await asyncio.sleep(0.3)
    await sup.stop()

    echoed = [
        ln.text.split("command: ", 1)[1]
        for ln in sup.console.snapshot()
        if "command: " in ln.text and ("a" in ln.text or "b" in ln.text)
    ]
    relevant = [e for e in echoed if e in (a, b)]
    assert len(relevant) == 40  # all delivered, each a whole line
    assert set(relevant) == {a, b}


async def test_submitted_command_is_echoed_to_all_clients(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    console = Console(sup)
    await sup.start()

    seen_a: list[tuple[str, str]] = []
    seen_b: list[tuple[str, str]] = []

    async def watch(bucket: list[tuple[str, str]]) -> None:
        async for line in console.stream():
            if line.kind is LineKind.COMMAND:
                bucket.append((line.kind, line.text))
                return

    ta = asyncio.create_task(watch(seen_a))
    tb = asyncio.create_task(watch(seen_b))
    await asyncio.sleep(0.1)
    await console.submit_command("list")
    await asyncio.gather(ta, tb)
    await sup.stop()
    assert seen_a == seen_b == [(LineKind.COMMAND, "list")]


async def test_command_rejected_when_not_running(make_supervisor) -> None:
    sup: Supervisor = make_supervisor()
    console = Console(sup)
    with pytest.raises(NotRunningError):
        await console.submit_command("list")
    # nothing was echoed
    assert not [ln for ln in sup.console.snapshot() if ln.kind is LineKind.COMMAND]


# -- 5.5 reconnection ---------------------------------------------
async def test_disconnect_and_reconnect_redelivers_history_and_leaves_others_intact(
    make_supervisor,
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    console = Console(sup)
    await sup.start()

    # steady client stays connected throughout
    steady: list[str] = []

    async def steady_reader() -> None:
        async for line in console.stream():
            steady.append(line.text)

    steady_task = asyncio.create_task(steady_reader())

    # first client connects, reads some, disconnects
    first: list[str] = []
    async for line in console.stream():
        first.append(line.text)
        if len(first) >= 3:
            break  # disconnect

    await asyncio.sleep(0.1)
    assert sup.state.value == "running"  # server unaffected by the disconnect

    # reconnect: retained history is redelivered
    reconnected: list[str] = []
    async for line in console.stream():
        reconnected.append(line.text)
        if len(reconnected) >= 3:
            break
    assert reconnected[:3] == first[:3]  # same retained history

    steady_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await steady_task
    await sup.stop()
    assert len(steady) >= 3  # the steady client kept receiving throughout
