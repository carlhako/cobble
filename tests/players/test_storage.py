"""Storage foundation (tasks 1.1-1.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cobble.players.storage import (
    END_OBSERVED,
    END_RECONSTRUCTED,
    END_SERVER_STOP,
    SCHEMA_VERSION,
    PlayerHistoryError,
    open_store,
)


def _dt(offset_seconds: float = 0.0) -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds)


# -- 1.1 idempotent schema ----------------------------------------
def test_opening_twice_leaves_schema_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "cobble.db"
    first = open_store(db)
    first.open_session("x1", "Alex", _dt())
    first.close()

    second = open_store(db)
    # Schema still there and the row from the first open survives.
    assert second._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    tables = {
        r[0] for r in second._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"players", "sessions", "schema_version"} <= tables
    second.close()


def test_wal_mode_is_enabled(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    store.close()


# -- 1.2 schema version -----------------------------------------
def test_schema_version_written_on_creation(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    assert store._conn.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION
    store.close()


def test_unknown_future_version_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "cobble.db"
    store = open_store(db)
    store._conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 5,))
    store.close()

    with pytest.raises(PlayerHistoryError) as excinfo:
        open_store(db)
    assert "newer" in str(excinfo.value)


# -- 1.3 tables and fields ------------------------------------
def test_session_roundtrips_every_field(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    sid = store.open_session("x1", "Alex", _dt(0))
    store.record_spawn("x1", _dt(6))
    store.close_session("x1", _dt(3600), END_OBSERVED)

    row = store._conn.execute(
        "SELECT xuid, gamertag, connected_at, spawned_at, disconnected_at, end_reason "
        "FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    assert row == (
        "x1",
        "Alex",
        _dt(0).isoformat(),
        _dt(6).isoformat(),
        _dt(3600).isoformat(),
        END_OBSERVED,
    )
    store.close()


def test_session_with_null_spawn_is_retained(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", _dt(0))
    store.close_session("x1", _dt(4), END_OBSERVED)
    row = store._conn.execute(
        "SELECT spawned_at, disconnected_at FROM sessions WHERE xuid = 'x1'"
    ).fetchone()
    assert row[0] is None and row[1] == _dt(4).isoformat()
    store.close()


# -- 1.4 write operations --------------------------------------
def test_second_world_entry_leaves_the_first_intact(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", _dt(0))
    store.record_spawn("x1", _dt(6))
    store.record_spawn("x1", _dt(600))  # a later spawn in the same session
    spawn = store._conn.execute("SELECT spawned_at FROM sessions WHERE xuid = 'x1'").fetchone()[0]
    assert spawn == _dt(6).isoformat()
    store.close()


def test_close_session_records_reason_and_time(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", _dt(0))
    closed = store.close_session("x1", _dt(120), END_SERVER_STOP)
    assert closed == 1
    assert store.close_session("x1", _dt(200), END_OBSERVED) == 0  # nothing open now
    store.close()


def test_reconnect_starts_a_distinct_session(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", _dt(0))
    store.close_session("x1", _dt(100), END_OBSERVED)
    store.open_session("x1", "Alex", _dt(106))  # ~6s later, per the captured data
    rows = store._conn.execute(
        "SELECT connected_at, disconnected_at FROM sessions WHERE xuid = 'x1' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] != rows[1]
    store.close()


# -- 1.5 roster / session queries -------------------------------
def test_totals_equal_the_sum_of_session_durations(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", _dt(0))
    store.close_session("x1", _dt(100), END_OBSERVED)
    store.open_session("x1", "Alex", _dt(200))
    store.close_session("x1", _dt(350), END_OBSERVED)

    roster = store.roster(now=_dt(1000))
    assert len(roster) == 1
    assert roster[0].total_seconds == pytest.approx(250.0)
    assert roster[0].session_count == 2
    assert roster[0].online is False
    store.close()


def test_open_session_contributes_elapsed_time(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", _dt(0))
    entry = store.roster(now=_dt(90))[0]
    assert entry.total_seconds == pytest.approx(90.0)
    assert entry.online is True
    store.close()


def test_player_with_no_closed_sessions_reports_zero_not_error(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", _dt(0))
    # roster asked with now == connect time: zero elapsed, no error.
    entry = store.roster(now=_dt(0))[0]
    assert entry.total_seconds == pytest.approx(0.0)
    assert entry.session_count == 1
    store.close()


def test_empty_roster_is_empty_list(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    assert store.roster(now=_dt(0)) == []
    assert store.recorded_since() is None
    store.close()


def test_sessions_for_orders_most_recent_first_and_unknown_raises(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "Alex", _dt(0))
    store.close_session("x1", _dt(50), END_OBSERVED)
    store.open_session("x1", "Alex", _dt(100))
    store.close_session("x1", _dt(160), END_RECONSTRUCTED)

    rows = store.sessions_for("x1", now=_dt(1000))
    assert [r.connected_at for r in rows] == [_dt(100).isoformat(), _dt(0).isoformat()]
    assert rows[0].approximate is True and rows[1].approximate is False
    assert rows[0].duration_seconds == pytest.approx(60.0)

    with pytest.raises(KeyError):
        store.sessions_for("does-not-exist", now=_dt(1000))
    store.close()


def test_rename_keeps_history_and_updates_display_name(tmp_path: Path) -> None:
    store = open_store(tmp_path / "cobble.db")
    store.open_session("x1", "OldName", _dt(0))
    store.close_session("x1", _dt(60), END_OBSERVED)
    store.open_session("x1", "NewName", _dt(120))
    store.close_session("x1", _dt(180), END_OBSERVED)

    entry = store.roster(now=_dt(1000))[0]
    assert entry.gamertag == "NewName"
    assert entry.session_count == 2
    per_session = [r.gamertag for r in store.sessions_for("x1", now=_dt(1000))]
    assert per_session == ["NewName", "OldName"]
    store.close()
