"""Section 4: configuration-in-effect snapshot and pending changes (tasks 4.1-4.3)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from cobble.acquisition.layout import Layout
from cobble.config.service import ConfigService
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio

BASE = "server-name=Dedicated Server\ndifficulty=easy\nmax-players=10\nlevel-name=Bedrock level\n"


class Wired:
    def __init__(self, sup: Supervisor, svc: ConfigService, props) -> None:
        self.sup = sup
        self.svc = svc
        self.props = props


@pytest.fixture
def wired(install_fake_bedrock: Callable[..., Settings]) -> Wired:
    settings = install_fake_bedrock(readiness_timeout=3.0, shutdown_timeout=3.0)
    layout = Layout.from_settings(settings)
    props = layout.data_dir / "server.properties"
    props.write_text(BASE)
    sup = Supervisor(settings)
    return Wired(sup, ConfigService(settings, layout, sup), props)


async def test_snapshot_taken_at_start_then_replaced_then_cleared(wired: Wired) -> None:
    # 4.1
    assert wired.sup.config_snapshot is None

    await wired.sup.start()
    assert wired.sup.config_snapshot is not None
    assert wired.sup.config_snapshot["max-players"] == "10"

    wired.props.write_text(BASE.replace("max-players=10", "max-players=20"))
    await wired.sup.restart()
    assert wired.sup.config_snapshot["max-players"] == "20"  # replaced at the new start

    await wired.sup.stop()
    assert wired.sup.config_snapshot is None


async def test_pending_reports_changes_from_cobble_and_from_a_direct_edit(wired: Wired) -> None:
    # 4.2
    await wired.sup.start()
    assert wired.svc.pending() == []

    wired.svc.write({"difficulty": "hard"})  # change through cobble
    wired.props.write_text(
        wired.props.read_text().replace("max-players=10", "max-players=15")
    )  # direct edit

    pending = {c.key: (c.saved, c.in_effect) for c in wired.svc.pending()}
    assert pending["difficulty"] == ("hard", "easy")
    assert pending["max-players"] == ("15", "10")

    await wired.sup.stop()


async def test_comment_or_reorder_edit_produces_no_pending_changes(wired: Wired) -> None:
    # 4.2 — comparison is over effective values
    await wired.sup.start()
    wired.props.write_text(
        "# a new comment\nmax-players=10\ndifficulty=easy\n"
        "level-name=Bedrock level\nserver-name=Dedicated Server\n"
    )
    assert wired.svc.pending() == []
    await wired.sup.stop()


async def test_nothing_is_pending_while_the_server_is_stopped(wired: Wired) -> None:
    wired.props.write_text(BASE.replace("difficulty=easy", "difficulty=hard"))
    assert wired.sup.state is RunState.STOPPED
    assert wired.svc.pending() == []


async def test_pending_clears_across_a_restart_via_the_new_snapshot(wired: Wired) -> None:
    # 4.3
    await wired.sup.start()
    wired.svc.write({"difficulty": "hard"})
    assert [c.key for c in wired.svc.pending()] == ["difficulty"]

    await wired.sup.restart()
    assert wired.svc.pending() == []  # the new snapshot already matches the file
    assert wired.sup.config_snapshot["difficulty"] == "hard"

    await wired.sup.stop()
