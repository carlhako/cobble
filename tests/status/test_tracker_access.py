"""The access block in the status snapshot and its push (tasks 8.1-8.3)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from cobble.access.enforcement import EnforcementTracker
from cobble.acquisition.layout import Layout
from cobble.config.service import ConfigService
from cobble.events.model import AllowlistEnabled
from cobble.settings import Settings
from cobble.status.tracker import StatusTracker
from cobble.supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio

BASE = "difficulty=easy\nallow-list=false\nlevel-name=Bedrock level\n"


class FakeAccess:
    def __init__(self, bans: int = 0) -> None:
        self._bans = bans

    def banned_count(self) -> int:
        return self._bans


class Wired:
    def __init__(self, sup, tracker, svc, enforcement, access) -> None:
        self.sup = sup
        self.tracker = tracker
        self.svc = svc
        self.enforcement = enforcement
        self.access = access


@pytest.fixture
def wired(install_fake_bedrock: Callable[..., Settings]) -> Wired:
    settings = install_fake_bedrock(readiness_timeout=3.0, shutdown_timeout=3.0)
    layout = Layout.from_settings(settings)
    (layout.data_dir / "server.properties").write_text(BASE)
    sup = Supervisor(settings)
    enforcement = EnforcementTracker()
    access = FakeAccess(bans=2)
    tracker = StatusTracker(sup)
    svc = ConfigService(settings, layout, sup, enforcement=enforcement)
    tracker._config = svc
    tracker._access = access
    sup.subscribe_state(enforcement.on_state_change)
    return Wired(sup, tracker, svc, enforcement, access)


# -- 8.1 the block appears; unobserved enforcement is "unknown" ---
async def test_access_block_appears_with_ban_count(wired: Wired) -> None:
    await wired.sup.start()
    block = wired.tracker.snapshot().access
    assert block is not None
    assert block["ban_count"] == 2
    assert block["running"] is True
    assert block["in_effect"] == "unknown"  # no transition observed yet
    await wired.sup.stop()


async def test_observed_enforcement_is_reported(wired: Wired) -> None:
    await wired.sup.start()
    wired.enforcement.on_event(AllowlistEnabled(raw="Turned on the allowlist"))
    block = wired.tracker.snapshot().access
    assert block["in_effect"] == "on"
    assert block["saved"] is False
    assert block["disagreement"] is True
    await wired.sup.stop()


# -- 8.2 stopped-server value is the next-start value, distinguishable --
async def test_stopped_server_reports_the_next_start_value_distinctly(wired: Wired) -> None:
    # file says allow-list on; server not running
    (wired.svc._path).write_text("allow-list=true\n")
    block = wired.tracker.snapshot().access
    assert block["running"] is False
    assert block["in_effect"] == "unknown"  # not an observed live value
    assert block["saved"] is True  # what the next start will apply

    await wired.sup.start()
    wired.enforcement.on_event(AllowlistEnabled(raw="Turned on the allowlist"))
    running_block = wired.tracker.snapshot().access
    assert running_block["running"] is True
    assert running_block["in_effect"] == "on"  # distinguishable from the stopped case
    await wired.sup.stop()


# -- 8.3 an enforcement change pushes a new snapshot -------------
async def test_enforcement_change_pushes_a_new_snapshot(wired: Wired) -> None:
    await wired.sup.start()
    stream = wired.tracker.stream()
    await stream.__anext__()  # the initial snapshot

    wired.tracker.on_event(AllowlistEnabled(raw="Turned on the allowlist"))
    pushed = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    assert pushed.access is not None
    await stream.aclose()
    await wired.sup.stop()
