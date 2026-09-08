"""Readiness reconciliation: baseline, adoption, repair, first-sight defaults
(tasks 4.1, 4.2, 4.4, 4.5, 4.6, 4.7, 4.8)."""

from __future__ import annotations

import pytest

from cobble.gamerules.manager import Classification
from cobble.gamerules.storage import REPORT_ADOPTION, REPORT_DEFAULTS, REPORT_REPAIR
from cobble.supervisor.supervisor import MaintenanceInProgressError
from tests.gamerules.conftest import FIXED_NOW


# -- 4.1 the four classifications --------------------------------
async def test_baseline_when_live_matches_the_record(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True, "pvp": True})
    env.store.write_record("world-a", {"mobGriefing": True, "pvp": True}, FIXED_NOW)

    outcome = await env.mgr.reconcile()
    assert outcome.classification is Classification.BASELINE
    assert env.store.read_report("world-a") is None
    assert env.svc.writes == []  # nothing written to the server


async def test_adoption_when_live_diverges_and_no_restore(make_manager) -> None:
    env = make_manager(values={"mobGriefing": False, "pvp": True})
    env.store.write_record("world-a", {"mobGriefing": True, "pvp": True}, FIXED_NOW)

    outcome = await env.mgr.reconcile()
    assert outcome.classification is Classification.ADOPTION
    assert outcome.rules == {"mobGriefing": False}


async def test_repair_when_diverged_on_first_readiness_after_restore(make_manager) -> None:
    env = make_manager(values={"mobGriefing": False, "pvp": True})
    env.store.write_record("world-a", {"mobGriefing": True, "pvp": True}, FIXED_NOW)
    env.store.set_restore_marker("world-a", FIXED_NOW)

    outcome = await env.mgr.reconcile()
    assert outcome.classification is Classification.REPAIR
    # the recorded value was written back to the server
    assert ("mobGriefing", True) in env.svc.writes
    assert outcome.rules == {"mobGriefing": True}


async def test_defaults_for_a_world_with_no_record(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True, "keepInventory": False})
    env.store.set_default("keepInventory", True)

    outcome = await env.mgr.reconcile()
    assert outcome.classification is Classification.DEFAULTS
    assert ("keepInventory", True) in env.svc.writes


# -- 4.2 adoption stores live, writes nothing, reports the diff --
async def test_adoption_stores_live_and_reports_exactly_the_diverged_rules(make_manager) -> None:
    env = make_manager(values={"mobGriefing": False, "pvp": False, "keepInventory": False})
    env.store.write_record(
        "world-a", {"mobGriefing": True, "pvp": False, "keepInventory": False}, FIXED_NOW
    )

    await env.mgr.reconcile()

    assert env.svc.writes == []  # the server is left as the operator set it
    rec = env.store.read_record("world-a")
    assert rec.values["mobGriefing"] is False  # live value adopted into the record
    report = env.store.read_report("world-a")
    assert report.kind == REPORT_ADOPTION
    assert report.rules == {"mobGriefing": False}  # exactly the diverged rule


async def test_no_divergence_reports_nothing(make_manager) -> None:
    env = make_manager(values={"pvp": True})
    env.store.write_record("world-a", {"pvp": True}, FIXED_NOW)
    await env.mgr.reconcile()
    assert env.store.read_report("world-a") is None


# -- 4.4 the marker is consumed on the first readiness ---------
async def test_repair_writes_back_names_rules_and_clears_marker(make_manager) -> None:
    env = make_manager(values={"mobGriefing": False, "pvp": False})
    env.store.write_record("world-a", {"mobGriefing": True, "pvp": True}, FIXED_NOW)
    env.store.set_restore_marker("world-a", FIXED_NOW)

    await env.mgr.reconcile()

    assert ("mobGriefing", True) in env.svc.writes
    assert ("pvp", True) in env.svc.writes
    report = env.store.read_report("world-a")
    assert report.kind == REPORT_REPAIR
    assert report.rules == {"mobGriefing": True, "pvp": True}
    assert env.store.restore_marker() is None  # consumed


async def test_marker_cleared_even_when_no_divergence(make_manager) -> None:
    env = make_manager(values={"pvp": True})
    env.store.write_record("world-a", {"pvp": True}, FIXED_NOW)
    env.store.set_restore_marker("world-a", FIXED_NOW)

    outcome = await env.mgr.reconcile()
    assert outcome.classification is Classification.BASELINE
    assert env.store.restore_marker() is None
    assert env.store.read_report("world-a") is None


# -- 4.5 the start after a repair adopts again ----------------
async def test_second_readiness_after_repair_adopts(make_manager) -> None:
    env = make_manager(values={"mobGriefing": False})
    env.store.write_record("world-a", {"mobGriefing": True}, FIXED_NOW)
    env.store.set_restore_marker("world-a", FIXED_NOW)

    first = await env.mgr.reconcile()
    assert first.classification is Classification.REPAIR
    # the repair wrote mobGriefing=true back; simulate the operator changing it
    # again in game before the next start
    env.svc.values["mobGriefing"] = False

    second = await env.mgr.reconcile()
    assert second.classification is Classification.ADOPTION


# -- 4.6 defaults applied, recorded, reported ----------------
async def test_defaults_applied_become_the_record_and_are_reported(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True, "keepInventory": False, "randomTickSpeed": 1})
    env.store.set_default("keepInventory", True)
    env.store.set_default("randomTickSpeed", 3)

    outcome = await env.mgr.reconcile()

    assert outcome.classification is Classification.DEFAULTS
    assert ("keepInventory", True) in env.svc.writes
    assert ("randomTickSpeed", 3) in env.svc.writes
    rec = env.store.read_record("world-a")
    assert rec.values["keepInventory"] is True
    assert rec.values["randomTickSpeed"] == 3
    report = env.store.read_report("world-a")
    assert report.kind == REPORT_DEFAULTS
    assert report.rules == {"keepInventory": True, "randomTickSpeed": 3}


# -- 4.7 defaults never reach a recorded world; no-defaults first sight --
async def test_defaults_not_applied_to_a_recorded_world(make_manager) -> None:
    env = make_manager(values={"keepInventory": False})
    env.store.write_record("world-a", {"keepInventory": False}, FIXED_NOW)
    env.store.set_default("keepInventory", True)

    outcome = await env.mgr.reconcile()
    assert outcome.classification is Classification.BASELINE
    assert env.svc.writes == []  # the default did not reach the server
    assert env.store.read_report("world-a") is None


async def test_first_sight_with_no_defaults_is_recorded_as_is(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True, "pvp": False})

    outcome = await env.mgr.reconcile()
    assert outcome.classification is Classification.BASELINE
    assert env.svc.writes == []
    rec = env.store.read_record("world-a")
    assert rec.values == {"mobGriefing": True, "pvp": False}
    assert rec.sampled_at == FIXED_NOW.isoformat()
    assert env.store.read_report("world-a") is None


# -- 4.8 gamerule writes refused during maintenance, reads ok --
async def test_write_refused_during_maintenance(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True})
    env.sup.maintenance = "backing_up"

    with pytest.raises(MaintenanceInProgressError) as ei:
        await env.mgr.write_rule("mobGriefing", False)
    assert "backing_up" in str(ei.value)
    assert env.svc.writes == []


async def test_read_succeeds_during_maintenance(make_manager) -> None:
    env = make_manager(values={"mobGriefing": True})
    env.sup.maintenance = "restoring"
    view = await env.mgr.current_view()
    assert view.rules.get("mobGriefing").value is True
