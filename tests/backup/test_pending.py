"""import-backup-archive 4.1: applying a staged restore at startup."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import cobble.backup.pending as pending_mod
from cobble.backup.pending import (
    apply_pending_state,
    marker_path,
    pending_dir,
    stage_state,
    write_marker,
)


def _stage(state: Path, staged: dict[str, str], *, was_running: bool = True) -> None:
    src = state.parent / "extracted-cobble-state"
    src.mkdir(parents=True)
    for name, text in staged.items():
        (src / name).write_text(text)
    entries = stage_state(src, state)
    write_marker(
        state,
        entries=entries,
        label="cobble-backup-x.tar.gz",
        level_name="W",
        replaced_capture="cobble-backup-replaced.tar.gz",
        was_running=was_running,
    )


def test_nothing_pending_is_a_no_op(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "a.json").write_text("live")
    assert apply_pending_state(state) is None
    assert (state / "a.json").read_text() == "live"


def test_a_staged_directory_without_a_marker_is_discarded(tmp_path: Path) -> None:
    state = tmp_path / "state"
    pending_dir(state).mkdir(parents=True)
    (pending_dir(state) / "a.json").write_text("staged")
    assert apply_pending_state(state) is None
    assert not pending_dir(state).exists()


def test_staging_drops_the_sources_instance_local_entries(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "release_check.json").write_text("dest")
    (state / "upgrade_pending.json").write_text("dest")
    _stage(
        state,
        {
            "cobble.db": "source-db",
            "release_check.json": "source",
            "upgrade_pending.json": "source",
            "runtime.json": '{"desired_running": false}',
        },
        was_running=True,
    )
    result = apply_pending_state(state)
    assert result is not None and result.error is None
    assert (state / "cobble.db").read_text() == "source-db"
    assert (state / "release_check.json").read_text() == "dest"
    assert (state / "upgrade_pending.json").read_text() == "dest"
    # The destination's run state before the restore wins over the source's.
    assert json.loads((state / "runtime.json").read_text()) == {"desired_running": True}


def test_an_io_failure_keeps_the_marker_and_reports(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    _stage(state, {"cobble.db": "source-db", "updates.json": "source"})

    def failing_move(src, dst):
        raise OSError("disk went away")

    monkeypatch.setattr(pending_mod.shutil, "move", failing_move)
    result = apply_pending_state(state)
    assert result is not None
    assert result.error and "disk went away" in result.error
    assert result.replaced_capture == "cobble-backup-replaced.tar.gz"
    assert marker_path(state).is_file()


def test_an_interrupted_swap_finishes_on_the_next_start(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "old.json").write_text("live-only")
    _stage(state, {"a.json": "A", "b.json": "B"})

    real_move = shutil.move
    calls = {"n": 0}

    def move_once_then_fail(src, dst):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("interrupted")
        return real_move(src, dst)

    monkeypatch.setattr(pending_mod.shutil, "move", move_once_then_fail)
    assert apply_pending_state(state).error == "interrupted"
    monkeypatch.undo()

    result = apply_pending_state(state)
    assert result is not None and result.error is None
    assert (state / "a.json").read_text() == "A"
    assert (state / "b.json").read_text() == "B"
    assert not (state / "old.json").exists()
    assert not marker_path(state).exists()


def test_an_unreadable_marker_is_discarded_and_reported(tmp_path: Path) -> None:
    state = tmp_path / "state"
    pending_dir(state).mkdir(parents=True)
    marker_path(state).write_text("{not json")
    result = apply_pending_state(state)
    assert result is not None and result.error
    assert not marker_path(state).exists()
    assert not pending_dir(state).exists()


@pytest.mark.parametrize("was_running", [True, False])
def test_the_marker_records_the_prior_run_state(tmp_path: Path, was_running: bool) -> None:
    state = tmp_path / "state"
    state.mkdir()
    _stage(state, {"x.json": "{}"}, was_running=was_running)
    result = apply_pending_state(state)
    assert result is not None and result.was_running is was_running
