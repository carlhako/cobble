"""Ban storage failures are logged and non-raising (task 3.5)."""

from __future__ import annotations

from cobble.access.enforcement import EnforcementTracker
from cobble.access.service import AccessService
from cobble.access.store import BanStoreError
from cobble.events.model import PlayerConnected, ServerReady
from tests.access.fakes import FakeConsole, FakeSupervisor


class RaisingBanStore:
    """Every method raises, to prove the service swallows it."""

    def __getattr__(self, _name):
        def _raise(*_a, **_k):
            raise BanStoreError("the ban table is gone")

        return _raise


def _service() -> AccessService:
    return AccessService(
        FakeConsole(),
        FakeSupervisor(),
        EnforcementTracker(),
        saved_allow_list=lambda: False,
        ban_store=RaisingBanStore(),
    )


def test_safe_reads_degrade_rather_than_raise() -> None:
    svc = _service()
    assert svc.is_banned("x1") is False
    assert svc.ban_record("x1") is None
    assert svc.active_bans() == []
    assert svc.banned_count() == 0


async def test_the_event_pipeline_is_unaffected_by_a_raising_ban_store() -> None:
    svc = _service()
    # feeding events through the bus callback must not propagate the storage error
    svc.on_event(
        PlayerConnected(raw="Player connected: Alex, xuid: x1", xuid="x1", gamertag="Alex")
    )
    svc.on_event(ServerReady(raw="Server started."))
    await svc.aclose()
