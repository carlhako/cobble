"""The identity service (server-identity spec, tasks 2.1-2.3)."""

from __future__ import annotations

import asyncio
import logging
import os
import stat

import pytest

from cobble.console.console import InternalQueryError
from cobble.events.model import ServerReady
from cobble.identity.service import (
    IdentitySaveError,
    IdentityService,
    is_save_reply,
)
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import MaintenanceInProgressError, NotRunningError

SAVED = (
    "[2026-10-05 10:00:00:000 INFO] Saved server identity key to /x/keys/server_identity_key.pem."
)
FAILED = "[2026-10-05 10:00:00:000 INFO] Failed to save server identity key to /x/keys/k.pem."
STATUS = "[2026-10-05 10:00:00:000 INFO] A saved server identity key exists at /x/keys/k.pem."


class FakeSupervisor:
    def __init__(self, running: bool = True) -> None:
        self.state = RunState.RUNNING if running else RunState.STOPPED
        self.maintenance: str | None = None

    async def wait_for_state(self, *targets):
        return self.state


class FakeConsole:
    """Answers ``serveridentity save`` and writes the key file when it succeeds."""

    def __init__(self, data_dir, *, reply: str = SAVED, write: bool = True, delay: float = 0.0):
        self.data_dir = data_dir
        self.reply = reply
        self.write = write
        self.delay = delay
        self.queries: list[str] = []
        self.submitted: list[str] = []
        self.timeout = False

    async def submit_command(self, command: str) -> None:  # pragma: no cover - must not be used
        self.submitted.append(command)

    async def query(self, command, matcher, *, reply_timeout=5.0):
        self.queries.append(command)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.timeout:
            raise InternalQueryError("no reply")
        assert matcher(self.reply)
        if self.write and self.reply == SAVED:
            key = self.data_dir / "keys" / "server_identity_key.pem"
            key.parent.mkdir(exist_ok=True)
            key.write_text("PEM")
        return self.reply


def _svc(tmp_path, *, running=True, **console_kw):
    sup = FakeSupervisor(running)
    console = FakeConsole(tmp_path, **console_kw)
    return IdentityService(console, sup, tmp_path), console, sup


def _put_key(tmp_path, content="PEM"):
    key = tmp_path / "keys" / "server_identity_key.pem"
    key.parent.mkdir(exist_ok=True)
    key.write_text(content)
    return key


# -- 2.1 ----------------------------------------------------------------
@pytest.mark.parametrize("running", [True, False])
def test_state_reads_the_file_alone(tmp_path, running):
    svc, console, _ = _svc(tmp_path, running=running)
    assert svc.state().to_dict() == {"saved": False, "running": running}
    _put_key(tmp_path)
    assert svc.state().to_dict() == {"saved": True, "running": running}
    assert console.queries == [] and console.submitted == []


def test_matchers_accept_real_replies_and_reject_status():
    assert is_save_reply(SAVED)
    assert is_save_reply(FAILED)
    assert is_save_reply("Saved server identity key to /a/b.pem.")
    assert not is_save_reply(STATUS)
    assert not is_save_reply("No saved server identity key exists at /a/b.pem.")


# -- 2.2 ----------------------------------------------------------------
async def test_save_issues_serveridentity_save_through_query(tmp_path):
    svc, console, _ = _svc(tmp_path)
    state = await svc.save_running()
    assert console.queries == ["serveridentity save"]
    assert console.submitted == []
    assert state.saved is True


async def test_save_issues_nothing_when_the_key_exists(tmp_path):
    key = _put_key(tmp_path, "operator key")
    svc, console, _ = _svc(tmp_path)
    state = await svc.save_running()
    assert console.queries == []
    assert state.saved is True
    assert key.read_text() == "operator key"


async def test_save_while_stopped_raises_not_running(tmp_path):
    svc, console, _ = _svc(tmp_path, running=False)
    with pytest.raises(NotRunningError):
        await svc.save_running()
    assert console.queries == []


async def test_save_during_maintenance_is_refused(tmp_path):
    svc, console, sup = _svc(tmp_path)
    sup.maintenance = "backup"
    with pytest.raises(MaintenanceInProgressError):
        await svc.save_running()
    assert console.queries == []


async def test_failed_reply_raises_with_the_reply(tmp_path):
    svc, _, _ = _svc(tmp_path, reply=FAILED)
    with pytest.raises(IdentitySaveError) as ei:
        await svc.save_running()
    assert "Failed to save server identity key" in ei.value.reason
    assert svc.state().saved is False


async def test_timeout_raises_identity_save_error(tmp_path):
    svc, console, _ = _svc(tmp_path)
    console.timeout = True
    with pytest.raises(IdentitySaveError):
        await svc.save_running()


async def test_saved_reply_without_a_file_is_an_error(tmp_path):
    svc, _, _ = _svc(tmp_path, write=False)
    with pytest.raises(IdentitySaveError):
        await svc.save_running()
    assert svc.state().saved is False


async def test_concurrent_saves_issue_one_command(tmp_path):
    svc, console, _ = _svc(tmp_path, delay=0.05)
    a, b = await asyncio.gather(svc.save_running(), svc.save_running())
    assert console.queries == ["serveridentity save"]
    assert a.saved and b.saved


async def test_looser_modes_are_tightened_after_a_save(tmp_path):
    (tmp_path / "keys").mkdir()
    os.chmod(tmp_path / "keys", 0o755)
    svc, console, _ = _svc(tmp_path)
    orig = console.query

    async def loose(command, matcher, **kw):
        r = await orig(command, matcher, **kw)
        os.chmod(tmp_path / "keys" / "server_identity_key.pem", 0o644)
        return r

    console.query = loose
    await svc.save_running()
    assert stat.S_IMODE((tmp_path / "keys").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "keys" / "server_identity_key.pem").stat().st_mode) == 0o600


# -- 2.3 ----------------------------------------------------------------
async def _drain():
    for _ in range(10):
        await asyncio.sleep(0)


async def test_readiness_without_a_key_issues_one_save(tmp_path):
    svc, console, _ = _svc(tmp_path)
    svc.on_event(ServerReady(raw="Server started."))
    await _drain()
    assert console.queries == ["serveridentity save"]
    assert svc.state().saved


async def test_readiness_with_a_key_issues_none(tmp_path):
    _put_key(tmp_path)
    svc, console, _ = _svc(tmp_path)
    svc.on_event(ServerReady(raw="Server started."))
    await _drain()
    assert console.queries == []


async def test_readiness_failure_is_logged_and_leaves_the_state_alone(tmp_path, caplog):
    svc, _, sup = _svc(tmp_path, reply=FAILED)
    with caplog.at_level(logging.WARNING):
        svc.on_event(ServerReady(raw="Server started."))
        await _drain()
    assert sup.state is RunState.RUNNING
    assert svc.state().saved is False
    assert any("server identity" in r.getMessage() for r in caplog.records)
