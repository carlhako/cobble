"""Section 2: the single upload staging slot."""

from __future__ import annotations

from pathlib import Path

from cobble.worldimport.staging import StagingSlot


def _slot(tmp_path: Path) -> StagingSlot:
    return StagingSlot(tmp_path / "state" / "import-staging")


# -- 2.1 lazy creation ---------------------------------------------
def test_slot_directory_is_created_lazily(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "runtime.json").write_text("{}")
    slot = _slot(tmp_path)
    assert not slot.root.exists()
    slot.held()  # a read does not create it
    assert not slot.root.exists()
    with slot.open_partial() as fh:
        fh.write(b"x")
    assert slot.root.is_dir()
    # unrelated state files untouched
    assert (tmp_path / "state" / "runtime.json").read_text() == "{}"


# -- 2.2 partial then rename -------------------------------------
def test_partial_is_not_reported_as_held(tmp_path: Path) -> None:
    slot = _slot(tmp_path)
    with slot.open_partial() as fh:
        fh.write(b"incomplete")
    assert slot.held() is None
    assert slot.partial_path.is_file()


def test_new_partial_does_not_overwrite_a_held_archive(tmp_path: Path) -> None:
    slot = _slot(tmp_path)
    with slot.open_partial() as fh:
        fh.write(b"first")
    slot.commit_partial()
    assert slot.held() is not None
    with slot.open_partial() as fh:
        fh.write(b"second-incomplete")
    # the held archive still has the first payload until the new one commits
    assert slot.archive_path.read_bytes() == b"first"


# -- 2.3 replace / clear / discard --------------------------------
def test_slot_holds_at_most_one_and_is_empty_after_each_path(tmp_path: Path) -> None:
    slot = _slot(tmp_path)
    for payload in (b"a", b"b", b"c"):
        with slot.open_partial() as fh:
            fh.write(payload)
        slot.commit_partial()
        assert slot.archive_path.read_bytes() == payload  # replace-on-upload

    slot.clear()  # clear-on-apply
    assert slot.held() is None and not slot.partial_path.exists()

    with slot.open_partial() as fh:
        fh.write(b"d")
    slot.commit_partial()
    slot.clear()  # discard
    assert slot.held() is None


# -- 2.4 startup sweep -----------------------------------------
def test_sweep_removes_an_archive_and_a_partial_from_a_previous_run(tmp_path: Path) -> None:
    slot = _slot(tmp_path)
    with slot.open_partial() as fh:
        fh.write(b"held")
    slot.commit_partial()
    slot.partial_path.write_bytes(b"leftover")
    slot.store_inspection({"ok": True})

    StagingSlot(slot.root).sweep()

    assert not slot.archive_path.exists()
    assert not slot.partial_path.exists()
    assert not slot._inspection_path.exists()


# -- 2.5 inspection cache ------------------------------------
def test_inspection_cache_round_trips_and_invalidates_on_replace(tmp_path: Path) -> None:
    slot = _slot(tmp_path)
    with slot.open_partial() as fh:
        fh.write(b"one")
    slot.commit_partial()
    slot.store_inspection({"ok": True, "inspection": {"world_name": "W"}})
    assert slot.load_inspection() == {"ok": True, "inspection": {"world_name": "W"}}

    with slot.open_partial() as fh:
        fh.write(b"two-different-size")
    slot.commit_partial()  # drops the cache
    assert slot.load_inspection() is None
