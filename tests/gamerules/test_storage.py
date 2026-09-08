"""The per-world gamerule store (tasks 3.1, 3.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cobble.gamerules.storage import (
    REPORT_ADOPTION,
    REPORT_REPAIR,
    GameruleStorageError,
    Report,
    open_store,
)


def _dt(offset: float = 0.0) -> datetime:
    return datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset)


def _tables(store) -> set[str]:
    return {
        r[0]
        for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


# -- 3.1 idempotent schema -----------------------------------------
def test_opening_twice_leaves_schema_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "cobble.db"
    first = open_store(db)
    first.write_record("world-a", {"mobGriefing": True}, _dt())
    tables_first = _tables(first)
    first.close()

    second = open_store(db)
    assert _tables(second) == tables_first
    assert {
        "gamerule_records",
        "gamerule_defaults",
        "gamerule_restore_marker",
        "gamerule_reports",
    } <= _tables(second)
    # the row from the first open survives
    assert second.read_record("world-a").values == {"mobGriefing": True}
    second.close()


def test_coexists_with_the_player_schema(tmp_path: Path) -> None:
    from cobble.players.storage import open_store as open_players

    db = tmp_path / "cobble.db"
    players = open_players(db)
    players.open_session("x1", "Alex", _dt())
    grules = open_store(db)
    grules.write_record("world-a", {"pvp": False}, _dt())
    # both schemas usable on the same file
    assert grules.read_record("world-a").values == {"pvp": False}
    assert players._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    players.close()
    grules.close()


# -- 3.2 per-world record read / write / existence ----------------
def test_two_worlds_keep_independent_records(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.write_record("world-a", {"mobGriefing": True, "randomTickSpeed": 1}, _dt())
    store.write_record("world-b", {"mobGriefing": False, "randomTickSpeed": 3}, _dt(10))

    a = store.read_record("world-a")
    b = store.read_record("world-b")
    assert a.values == {"mobGriefing": True, "randomTickSpeed": 1}
    assert b.values == {"mobGriefing": False, "randomTickSpeed": 3}
    assert a.sampled_at == _dt().isoformat()

    # rewriting world-a does not touch world-b
    store.write_record("world-a", {"mobGriefing": False}, _dt(20))
    assert store.read_record("world-a").values == {"mobGriefing": False}
    assert store.read_record("world-b").values == {"mobGriefing": False, "randomTickSpeed": 3}
    store.close()


def test_unrecorded_world_is_unread_not_empty(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    assert store.has_record("never-seen") is False
    assert store.read_record("never-seen") is None  # not {} — nothing is invented
    store.write_record("never-seen", {}, _dt())
    assert store.has_record("never-seen") is True
    assert store.read_record("never-seen").values == {}
    store.close()


# -- preferred defaults ------------------------------------------
def test_defaults_set_read_and_cleared(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    assert store.read_defaults() == {}
    store.set_default("keepInventory", True)
    store.set_default("randomTickSpeed", 3)
    assert store.read_defaults() == {"keepInventory": True, "randomTickSpeed": 3}
    store.set_default("keepInventory", False)  # overwrite
    assert store.read_defaults()["keepInventory"] is False
    store.clear_default("keepInventory")
    assert store.read_defaults() == {"randomTickSpeed": 3}
    store.close()


# -- restore marker --------------------------------------------
def test_restore_marker_is_set_read_and_consumed_by_world(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    assert store.restore_marker() is None
    store.set_restore_marker("world-a", _dt())
    assert store.restore_marker() == "world-a"
    # a marker for another world is left in place
    assert store.take_restore_marker("world-b") is False
    assert store.restore_marker() == "world-a"
    # consuming the matching world removes it
    assert store.take_restore_marker("world-a") is True
    assert store.restore_marker() is None
    store.close()


# -- unacknowledged report -----------------------------------
def test_report_write_read_replace_and_clear(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    assert store.read_report("world-a") is None
    store.write_report(Report("world-a", REPORT_ADOPTION, _dt().isoformat(), {"pvp": False}))
    got = store.read_report("world-a")
    assert got.kind == REPORT_ADOPTION
    assert got.rules == {"pvp": False}
    # a newer report replaces the old one
    store.write_report(
        Report("world-a", REPORT_REPAIR, _dt(5).isoformat(), {"mobGriefing": True})
    )
    assert store.read_report("world-a").kind == REPORT_REPAIR
    store.clear_report("world-a")
    assert store.read_report("world-a") is None
    store.close()


# -- storage errors surface as GameruleStorageError -----------
def test_operations_on_a_closed_store_raise_storage_error(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.close()
    with pytest.raises(GameruleStorageError):
        store.read_record("world-a")
