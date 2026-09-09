"""The access service asserting saved enforcement at readiness (task 2.4)."""

from __future__ import annotations

import asyncio

import pytest

from cobble.access.enforcement import Enforcement, EnforcementTracker
from cobble.access.service import AccessService
from cobble.events.model import ServerReady
from cobble.supervisor.supervisor import NotRunningError
from tests.access.fakes import FakeConsole, FakeSupervisor


def _service(*, running=True, saved_on=True):
    console = FakeConsole(running=running)
    sup = FakeSupervisor(running=running)
    tracker = EnforcementTracker()
    svc = AccessService(console, sup, tracker, saved_allow_list=lambda: saved_on)
    return svc, console, sup, tracker


async def _drain() -> None:
    # let the fire-and-forget readiness task run
    for _ in range(5):
        await asyncio.sleep(0)


async def test_readiness_asserts_the_saved_value_to_the_server() -> None:
    svc, console, _sup, tracker = _service(saved_on=True)
    svc.on_event(ServerReady(raw="Server started."))
    await _drain()
    assert console.submitted == ["allowlist on"]
    assert tracker.state is Enforcement.ON


async def test_readiness_asserts_off_when_the_file_says_off() -> None:
    svc, console, _sup, tracker = _service(saved_on=False)
    svc.on_event(ServerReady(raw="Server started."))
    await _drain()
    assert console.submitted == ["allowlist off"]
    assert tracker.state is Enforcement.OFF


async def test_tracked_state_matches_the_file_after_the_assertion() -> None:
    svc, _console, _sup, tracker = _service(saved_on=True)
    # a stale observation from a previous process
    tracker.note(False)
    svc.on_event(ServerReady(raw="Server started."))
    await _drain()
    assert tracker.state is Enforcement.ON  # self-healed within one start


async def test_apply_enforcement_hook_issues_the_command() -> None:
    svc, console, _sup, _tracker = _service()
    svc.apply_enforcement(True)
    await _drain()
    assert console.submitted == ["allowlist on"]


async def test_set_enforcement_refused_when_not_running() -> None:
    svc, console, _sup, _tracker = _service(running=False)
    with pytest.raises(NotRunningError):
        await svc.set_enforcement(True)
    assert console.submitted == []
