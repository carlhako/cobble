"""Section 5: the configuration view in status and its push (tasks 5.1-5.2)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from cobble.acquisition.layout import Layout
from cobble.config.service import ConfigService
from cobble.settings import Settings
from cobble.status.tracker import StatusTracker
from cobble.supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio

BASE = "difficulty=easy\nmax-players=10\nlevel-name=Bedrock level\n"


class Wired:
    def __init__(self, sup: Supervisor, tracker: StatusTracker, svc: ConfigService) -> None:
        self.sup = sup
        self.tracker = tracker
        self.svc = svc


@pytest.fixture
def wired(install_fake_bedrock: Callable[..., Settings]) -> Wired:
    settings = install_fake_bedrock(readiness_timeout=3.0, shutdown_timeout=3.0)
    layout = Layout.from_settings(settings)
    (layout.data_dir / "server.properties").write_text(BASE)
    sup = Supervisor(settings)
    tracker = StatusTracker(sup)
    svc = ConfigService(settings, layout, sup, on_change=tracker.notify)
    tracker._config = svc  # the runtime wires this via the constructor arg
    return Wired(sup, tracker, svc)


async def test_config_view_counts_differing_settings_only_while_running(wired: Wired) -> None:
    # 5.1
    assert wired.tracker.snapshot().config.pending is False
    assert wired.tracker.snapshot().config.pending_count == 0

    await wired.sup.start()
    wired.svc.write({"difficulty": "hard", "max-players": "20"})
    snap = wired.tracker.snapshot()
    assert snap.config.pending is True
    assert snap.config.pending_count == 2

    await wired.sup.stop()
    assert wired.tracker.snapshot().config.pending is False
    assert wired.tracker.snapshot().config.pending_count == 0


async def test_saving_config_pushes_the_new_pending_state(wired: Wired) -> None:
    # 5.2 — save case
    await wired.sup.start()

    stream = wired.tracker.stream()
    await stream.__anext__()  # current snapshot

    wired.svc.write({"difficulty": "hard"})
    pushed = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    assert pushed.config.pending_count == 1

    await stream.aclose()
    await wired.sup.stop()


async def test_start_and_restart_push_the_pending_state(wired: Wired) -> None:
    # 5.2 — start / restart cases
    await wired.sup.start()
    wired.svc.write({"difficulty": "hard"})

    stream = wired.tracker.stream()
    assert (await stream.__anext__()).config.pending_count == 1

    await wired.sup.restart()  # a restart applies the change; pending clears
    snap = None
    for _ in range(20):
        snap = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
        if snap.run_state.value == "running":
            break
    assert snap is not None and snap.config.pending_count == 0

    await stream.aclose()
    await wired.sup.stop()
