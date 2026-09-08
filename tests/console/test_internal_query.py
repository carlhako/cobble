"""The silent internal console path (server-console spec; tasks 1.1-1.7).

Cobble's own queries reach the server's stdin without the command or its reply
appearing in the console stream delivered to clients.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

import cobble.api.console as console_api
from cobble.console.buffer import ConsoleBuffer, LineKind
from cobble.console.console import Console, InternalQueryError
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import NotRunningError


class FakeSup:
    """Minimal supervisor stand-in: a real console buffer, a settable run state,
    and a record of what was written to stdin."""

    def __init__(self, state: RunState = RunState.RUNNING) -> None:
        self.console = ConsoleBuffer(maxlen=200)
        self.state = state
        self.sent: list[str] = []

    async def send_command(self, command: str) -> None:
        self.sent.append(command)


async def _drain(console: Console, sink: list) -> asyncio.Task:
    task = asyncio.create_task(_reader(console, sink))
    await asyncio.sleep(0)  # let the subscriber register
    return task


async def _reader(console: Console, sink: list) -> None:
    async for line in console.stream():
        sink.append(line)


# -- 1.1 non-echoed submission -----------------------------------------
async def test_internal_query_reaches_stdin_and_is_not_echoed() -> None:
    sup = FakeSup()
    console = Console(sup)
    seen: list = []
    task = await _drain(console, seen)

    async def respond() -> None:
        await asyncio.sleep(0.02)
        sup.console.add_output("Gamerules: doDaylightCycle = true, mobGriefing = false, x = 1")

    _bg = asyncio.create_task(respond())
    reply = await console.query("gamerule", lambda t: t.count(" = ") >= 2)

    assert sup.sent == ["gamerule"]  # reached the server's stdin
    assert reply == "Gamerules: doDaylightCycle = true, mobGriefing = false, x = 1"
    await _bg

    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # No client saw the command or its reply.
    assert not any(ln.kind is LineKind.COMMAND for ln in seen)
    assert not any("Gamerules:" in ln.text for ln in seen)


# -- 1.2 one-shot reply capture, withheld from every subscriber -------
async def test_reply_returned_once_and_in_no_stream() -> None:
    sup = FakeSup()
    console = Console(sup)
    a: list = []
    b: list = []
    ta = await _drain(console, a)
    tb = await _drain(console, b)

    async def respond() -> None:
        await asyncio.sleep(0.02)
        sup.console.add_output("k1 = a, k2 = b, k3 = c")

    _bg = asyncio.create_task(respond())
    reply = await console.query("gamerule", lambda t: " = " in t)
    assert reply == "k1 = a, k2 = b, k3 = c"
    await _bg

    await asyncio.sleep(0.02)
    for t in (ta, tb):
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    assert not any("k1 = a" in ln.text for ln in a)
    assert not any("k1 = a" in ln.text for ln in b)


async def test_reply_withheld_from_history_on_reconnect() -> None:
    sup = FakeSup()
    console = Console(sup)

    async def respond() -> None:
        await asyncio.sleep(0.02)
        sup.console.add_output("k1 = a, k2 = b")

    _bg = asyncio.create_task(respond())
    await console.query("gamerule", lambda t: " = " in t)
    await _bg

    # A client connecting now must not replay the consumed reply from history.
    seen: list = []
    task = await _drain(console, seen)
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any("k1 = a" in ln.text for ln in seen)


# -- 1.3 unrelated output passes through -------------------------------
async def test_unrelated_output_still_delivered_during_a_query() -> None:
    sup = FakeSup()
    console = Console(sup)
    seen: list = []
    task = await _drain(console, seen)

    async def traffic() -> None:
        await asyncio.sleep(0.01)
        sup.console.add_output("[INFO] a player joined")
        sup.console.add_output("[INFO] weather changed")
        await asyncio.sleep(0.01)
        sup.console.add_output("ruleA = 1, ruleB = 2")  # the reply

    _bg = asyncio.create_task(traffic())
    reply = await console.query("gamerule", lambda t: " = " in t and "," in t)
    assert reply == "ruleA = 1, ruleB = 2"
    await _bg

    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    texts = [ln.text for ln in seen]
    assert "[INFO] a player joined" in texts
    assert "[INFO] weather changed" in texts
    assert "ruleA = 1, ruleB = 2" not in texts  # only the reply is withheld


# -- 1.4 timeout is abandoned, console keeps flowing ------------------
async def test_query_timeout_reports_failure_without_disrupting_console() -> None:
    sup = FakeSup()
    console = Console(sup)
    seen: list = []
    task = await _drain(console, seen)

    async def traffic() -> None:
        for _ in range(3):
            await asyncio.sleep(0.02)
            sup.console.add_output("[INFO] tick")

    _bg = asyncio.create_task(traffic())
    with pytest.raises(InternalQueryError):
        await console.query("gamerule", lambda _t: False, reply_timeout=0.1)
    await _bg

    # The console kept delivering output after the abandoned query.
    sup.console.add_output("[INFO] after")
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(ln.text == "[INFO] after" for ln in seen)
    assert any(ln.text == "[INFO] tick" for ln in seen)


# -- 1.5 the consumed line is logged --------------------------------
async def test_consumed_line_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    sup = FakeSup()
    console = Console(sup)

    async def respond() -> None:
        await asyncio.sleep(0.02)
        sup.console.add_output("k1 = a, k2 = b")

    _bg = asyncio.create_task(respond())
    with caplog.at_level(logging.INFO, logger="cobble.console"):
        await console.query("gamerule", lambda t: " = " in t)
    await _bg
    assert any(
        "internal query consumed console line" in r.message and "k1 = a" in r.message
        for r in caplog.records
    )


# -- 1.6 refused when the server is not running ---------------------
async def test_internal_query_refused_when_not_running() -> None:
    sup = FakeSup(state=RunState.STOPPED)
    console = Console(sup)
    seen: list = []
    task = await _drain(console, seen)

    with pytest.raises(NotRunningError):
        await console.query("gamerule", lambda _t: True)
    assert sup.sent == []  # not queued
    assert len(sup.console) == 0

    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert seen == []


# -- 1.7 the API console router cannot reach the silent path -------
def test_console_api_router_only_uses_submit_command() -> None:
    src = Path(console_api.__file__).read_text()
    assert "submit_command" in src
    assert ".query(" not in src  # the non-echoed path is never wired to a route


async def test_client_command_is_echoed_regardless_of_content() -> None:
    sup = FakeSup()
    console = Console(sup)
    seen: list = []
    task = await _drain(console, seen)

    # A client command that looks exactly like cobble's bulk read is still an
    # operator command: it is echoed.
    await console.submit_command("gamerule")
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(ln.kind is LineKind.COMMAND and ln.text == "gamerule" for ln in seen)
