"""Fixtures for the gamerule manager / API tests: a manager wired to a real
temporary store, with the store closed on teardown."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from cobble.gamerules.manager import GameruleManager
from cobble.gamerules.storage import GameruleStore, open_store
from tests.gamerules.fakes import FakeGameruleService, FakeSupervisor

FIXED_NOW = datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC)


@dataclass
class ManagerEnv:
    mgr: GameruleManager
    svc: FakeGameruleService
    sup: FakeSupervisor
    store: GameruleStore


@pytest.fixture
def make_manager(tmp_path):
    opened: list[GameruleStore] = []

    def _make(
        *, running=True, level="world-a", values=None, on_report=None, clock=None
    ) -> ManagerEnv:
        store = open_store(tmp_path / "cobble.db")
        opened.append(store)
        sup = FakeSupervisor(running=running, level_name=level)
        svc = FakeGameruleService(values if values is not None else {"mobGriefing": True})
        mgr = GameruleManager(
            svc,
            store,
            sup,
            lambda: level,
            on_report=on_report,
            clock=clock or (lambda: FIXED_NOW),
        )
        return ManagerEnv(mgr=mgr, svc=svc, sup=sup, store=store)

    yield _make
    for store in opened:
        store.close()
