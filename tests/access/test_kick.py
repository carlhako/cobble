"""Kick orchestration in the access service (tasks 4.1, 4.2, 4.5, 4.6)."""

from __future__ import annotations

import asyncio

import pytest

from cobble.access.enforcement import EnforcementTracker
from cobble.access.service import AccessService, KickResult, NotConnectedError
from cobble.events.model import RawOutput
from cobble.players.kick import KickIntentRegistry
from cobble.supervisor.supervisor import NotRunningError
from tests.access.fakes import FakeConsole, FakeSupervisor

ONLINE = {"x1"}


def _service(*, console=None, running=True, online=ONLINE):
    console = console or FakeConsole(running=running)
    sup = FakeSupervisor(running=running)
    registry = KickIntentRegistry()
    svc = AccessService(
        console,
        sup,
        EnforcementTracker(),
        saved_allow_list=lambda: False,
        kick_intents=registry,
        is_connected=lambda x: x in online,
    )
    return svc, console, registry


# -- 4.1 command echoed; resolves on the disconnect --------------
async def test_kick_echoes_the_command_and_resolves_on_the_departure() -> None:
    svc, console, registry = _service()
    task = asyncio.create_task(svc.kick("x1", "Alex", "afk too long"))
    await asyncio.sleep(0)
    assert console.submitted == ["kick Alex afk too long"]  # echoed path
    # the recorder observes the disconnect and satisfies the intent
    registry.satisfy("x1")
    result = await task
    assert isinstance(result, KickResult)
    assert result.confirmed is True
    assert result.unconfirmed is False and result.no_target is False


async def test_kick_command_is_echoed_to_console_subscribers(make_supervisor) -> None:
    # A real console over a fake server: the kick command reaches the buffer
    # every subscriber reads from (design.md D6 — echoed, not silent).
    from cobble.console.buffer import LineKind
    from cobble.console.console import Console

    sup = make_supervisor(shutdown_timeout=5.0)
    console = Console(sup)
    await sup.start()
    try:
        svc = AccessService(
            console,
            sup,
            EnforcementTracker(),
            saved_allow_list=lambda: False,
            kick_intents=KickIntentRegistry(),
            is_connected=lambda _x: True,
        )
        result = await svc.kick("x9", "Steve", wait_timeout=0.2)
        assert result.unconfirmed is True  # fake server sends no disconnect
        echoed = [ln.text for ln in sup.console.snapshot() if ln.kind is LineKind.COMMAND]
        assert "kick Steve" in echoed
    finally:
        await sup.aclose()


async def test_kick_without_a_reason_sends_just_the_name() -> None:
    svc, console, registry = _service()
    task = asyncio.create_task(svc.kick("x1", "Alex"))
    await asyncio.sleep(0)
    assert console.submitted == ["kick Alex"]
    registry.satisfy("x1")
    await task


# -- 4.2 intent is registered before the command reaches stdin ---
async def test_intent_exists_before_the_command_is_sent() -> None:
    seen: dict[str, bool] = {}

    class CheckingConsole(FakeConsole):
        async def submit_command(self, command: str) -> None:
            seen["intent_present"] = registry.active("x1") is not None
            await super().submit_command(command)

    svc, _console, registry = _service(console=CheckingConsole())
    task = asyncio.create_task(svc.kick("x1", "Alex"))
    await asyncio.sleep(0)
    registry.satisfy("x1")
    await task
    assert seen["intent_present"] is True


# -- 4.5 unconfirmed vs no-target, never a plain success ---------
async def test_no_departure_in_time_is_reported_unconfirmed() -> None:
    svc, _console, _registry = _service()
    result = await svc.kick("x1", "Alex", wait_timeout=0.05)
    assert result.unconfirmed is True
    assert result.confirmed is False
    assert result.no_target is False


async def test_no_targets_matched_selector_is_distinguished() -> None:
    svc, _console, _registry = _service()
    task = asyncio.create_task(svc.kick("x1", "Ghost", wait_timeout=0.1))
    await asyncio.sleep(0)
    svc.on_event(RawOutput(raw="[INFO] No targets matched selector"))
    result = await task
    assert result.no_target is True
    assert result.confirmed is False
    assert result.unconfirmed is False


# -- 4.6 refusals send nothing ---------------------------------
async def test_kick_refused_when_the_player_is_not_connected() -> None:
    svc, console, _registry = _service(online=set())
    with pytest.raises(NotConnectedError):
        await svc.kick("x1", "Alex")
    assert console.submitted == []


async def test_kick_refused_when_the_server_is_not_running() -> None:
    svc, console, _registry = _service(running=False)
    with pytest.raises(NotRunningError):
        await svc.kick("x1", "Alex")
    assert console.submitted == []
