"""Backup consistency for the player-history database (tasks 5.1-5.3)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cobble.acquisition.layout import Layout
from cobble.backup.artifact import BackupError
from cobble.backup.capture import capture_archive
from cobble.backup.service import _extract_over_layout
from cobble.players.storage import (
    DB_FILENAME,
    END_OBSERVED,
    PlayerHistoryError,
    open_store,
    quiesce_database,
)


# -- 5.1 quiesce empties the WAL -------------------------------
def test_quiesce_empties_wal_and_main_file_is_self_contained(tmp_path: Path) -> None:
    db = tmp_path / DB_FILENAME
    store = open_store(db)
    for i in range(20):
        store.open_session(f"x{i}", f"P{i}", datetime(2026, 1, 1, tzinfo=UTC))
        store.close_session(f"x{i}", datetime(2026, 1, 1, 0, 30, tzinfo=UTC), END_OBSERVED)
    wal = db.with_name(db.name + "-wal")
    assert wal.exists() and wal.stat().st_size > 0  # WAL is carrying pages

    quiesce_database(db)
    assert (not wal.exists()) or wal.stat().st_size == 0

    store.close()
    # A fresh reader, with no sidecar present, sees everything.
    if wal.exists():
        os.remove(wal)
    reopened = open_store(db)
    assert len(reopened.roster(now=datetime(2026, 1, 2, tzinfo=UTC))) == 20
    reopened.close()


def test_quiesce_missing_database_is_a_noop(tmp_path: Path) -> None:
    quiesce_database(tmp_path / "nope.db")  # must not raise


# -- 5.2 capture mid-write, restore, everything committed is there ----
def test_backup_captures_db_mid_write_and_restores_cleanly(tmp_path: Path) -> None:
    root = tmp_path / "srv"
    (root / "data").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    layout = Layout(bedrock_root=root, state_dir=root / "state", backup_dir=tmp_path / "b")

    store = open_store(layout.state_dir / DB_FILENAME)
    for i in range(5):
        store.open_session(f"x{i}", f"P{i}", datetime(2026, 1, 1, tzinfo=UTC))
        store.close_session(f"x{i}", datetime(2026, 1, 1, 1, tzinfo=UTC), END_OBSERVED)
    # An open, uncommitted-looking session and the connection still live: the
    # capture must still yield a database that opens.
    store.open_session("live", "Live", datetime(2026, 1, 1, 2, tzinfo=UTC))

    manifest = capture_archive(
        layout,
        layout.backup_dir,
        bedrock_version=None,
        shutdown_clean=True,
        now=datetime(2026, 1, 1, 3, tzinfo=UTC),
    )
    store.close()

    fresh = tmp_path / "restore"
    fresh_layout = Layout(bedrock_root=fresh, state_dir=fresh / "state", backup_dir=tmp_path / "b")
    (fresh / "data").mkdir(parents=True)
    (fresh / "state").mkdir(parents=True)
    _extract_over_layout(layout.backup_dir / manifest.archive, fresh_layout)

    restored = open_store(fresh_layout.state_dir / DB_FILENAME)
    roster = restored.roster(now=datetime(2026, 1, 2, tzinfo=UTC))
    assert {e.xuid for e in roster} == {"x0", "x1", "x2", "x3", "x4", "live"}
    restored.close()


# -- 5.3 quiesce failure fails the backup with a reason -------------
def test_backup_fails_with_a_reason_when_quiesce_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "srv"
    (root / "data").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    layout = Layout(bedrock_root=root, state_dir=root / "state", backup_dir=tmp_path / "b")

    def boom(_path: Path) -> None:
        raise PlayerHistoryError("checkpoint refused: database is busy")

    monkeypatch.setattr("cobble.backup.capture.quiesce_database", boom)

    with pytest.raises(BackupError) as excinfo:
        capture_archive(
            layout,
            layout.backup_dir,
            bedrock_version=None,
            shutdown_clean=True,
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert "quiesce" in str(excinfo.value)
    # Nothing dangling was left behind.
    assert list(layout.backup_dir.glob("*.tar.gz")) == []
