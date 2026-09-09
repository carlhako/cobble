"""The durable ban record (tasks 3.1-3.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cobble.access.store import open_ban_store


def _dt(offset: float = 0.0) -> datetime:
    return datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset)


def _tables(store) -> set[str]:
    return {r[0] for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# -- 3.1 idempotent schema --------------------------------------
def test_opening_twice_leaves_the_schema_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "cobble.db"
    first = open_ban_store(db)
    first.record_ban("x1", "Alex", "griefing", _dt())
    tables_first = _tables(first)
    first.close()

    second = open_ban_store(db)
    assert _tables(second) == tables_first
    assert "bans" in _tables(second)
    assert second.get("x1").reason == "griefing"  # the row survives
    second.close()


def test_coexists_with_the_player_and_gamerule_schemas(tmp_path: Path) -> None:
    from cobble.gamerules.storage import open_store as open_gamerules
    from cobble.players.storage import open_store as open_players

    db = tmp_path / "cobble.db"
    players = open_players(db)
    players.open_session("x1", "Alex", _dt())
    grules = open_gamerules(db)
    grules.write_record("world-a", {"pvp": False}, _dt())
    bans = open_ban_store(db)
    bans.record_ban("x1", "Alex", "", _dt())
    assert bans.is_banned("x1") is True
    for s in (players, grules, bans):
        s.close()


# -- 3.2 record / lift / query --------------------------------
def test_a_lifted_ban_stops_being_reported_but_stays_retrievable(tmp_path: Path) -> None:
    store = open_ban_store(tmp_path / "cobble.db")
    store.record_ban("x1", "Alex", "spawn camping", _dt())
    assert store.is_banned("x1") is True
    assert [r.xuid for r in store.active_bans()] == ["x1"]

    assert store.lift_ban("x1", _dt(60)) is True
    assert store.is_banned("x1") is False
    assert store.active_bans() == []
    assert store.count_active() == 0

    # the record itself — name and reason — remains available
    rec = store.get("x1")
    assert rec is not None
    assert rec.name == "Alex"
    assert rec.reason == "spawn camping"
    assert rec.active is False
    assert rec.lifted_at is not None
    store.close()


def test_lifting_a_ban_that_is_not_active_returns_false(tmp_path: Path) -> None:
    store = open_ban_store(tmp_path / "cobble.db")
    assert store.lift_ban("nobody", _dt()) is False
    store.close()


def test_re_banning_clears_a_prior_lift(tmp_path: Path) -> None:
    store = open_ban_store(tmp_path / "cobble.db")
    store.record_ban("x1", "Alex", "first", _dt())
    store.lift_ban("x1", _dt(10))
    store.record_ban("x1", "Alex", "again", _dt(20))
    assert store.is_banned("x1") is True
    assert store.get("x1").reason == "again"
    store.close()


# -- 3.3 ban state is not inferred from allowlist absence -----
def test_a_player_with_no_ban_record_is_not_banned(tmp_path: Path) -> None:
    store = open_ban_store(tmp_path / "cobble.db")
    # never banned, and (by construction) absent from any allowlist
    assert store.is_banned("never-seen") is False
    assert store.get("never-seen") is None
    store.close()


# -- 3.4 a ban survives a display-name change -----------------
def test_ban_applies_across_a_rename_and_keeps_the_ban_time_name(tmp_path: Path) -> None:
    store = open_ban_store(tmp_path / "cobble.db")
    store.record_ban("stable-xuid", "OldName", "harassment", _dt())
    # the player later changes their gamertag; the roster now shows "NewName",
    # but the ban is keyed by the stable identifier
    assert store.is_banned("stable-xuid") is True
    rec = store.get("stable-xuid")
    assert rec.name == "OldName"  # the name recorded at ban time is preserved
    store.close()
