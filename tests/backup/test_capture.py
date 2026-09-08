"""Section 3 (pure filesystem half): artifact format, capture, verify, store.

Tasks 3.1, 3.2, 3.5, 3.6, 3.7, 3.8.
"""

from __future__ import annotations

import gzip
from datetime import UTC, datetime

import pytest

from cobble.acquisition.layout import Layout
from cobble.backup.artifact import BackupError, Manifest, sidecar_for
from cobble.backup.capture import capture_archive, verify_archive
from cobble.backup.store import BackupStore
from cobble.settings import Settings


def _layout_with_state(tmp_settings: Settings) -> Layout:
    layout = Layout.from_settings(tmp_settings)
    layout.ensure_directories()
    (layout.data_dir / "server.properties").write_text("level-name=Home\n")
    (layout.data_dir / "worlds" / "Home" / "db").mkdir(parents=True)
    (layout.data_dir / "worlds" / "Home" / "db" / "CURRENT").write_bytes(b"leveldb")
    (layout.state_dir / "runtime.json").write_text("{}")
    return layout


def _capture(layout: Layout, *, version="1.26.45.1", clean=True, at=None) -> Manifest:
    return capture_archive(
        layout,
        layout.backup_dir,
        bedrock_version=version,
        shutdown_clean=clean,
        now=at or datetime.now(UTC),
    )


# -- 3.1 manifest ------------------------------------------------------
def test_manifest_round_trips(tmp_path) -> None:
    m = Manifest(
        captured_at="2026-09-07T04:00:00+00:00",
        bedrock_version="1.26.45.1",
        shutdown_clean=False,
        archive="cobble-backup-x.tar.gz",
        sha256="deadbeef",
        size_bytes=1234,
    )
    sidecar = tmp_path / "cobble-backup-x.tar.gz.json"
    m.write_atomic(sidecar)
    assert Manifest.read(sidecar) == m


def test_unreadable_manifest_is_reported_not_raised(tmp_path) -> None:
    bad = tmp_path / "cobble-backup-y.tar.gz.json"
    bad.write_text("{ not json")
    assert Manifest.try_read(bad) is None
    with pytest.raises(BackupError):
        Manifest.read(bad)
    with pytest.raises(BackupError):
        Manifest.read(tmp_path / "missing.json")


# -- 3.2 whole-directory capture ------------------------------------
def test_capture_takes_whole_directories_including_later_files(tmp_settings: Settings) -> None:
    layout = _layout_with_state(tmp_settings)
    _capture(layout)
    # A file that "did not exist when the code was written" is added and picked
    # up by the next capture with no code change.
    (layout.data_dir / "worlds" / "Home" / "level.dat").write_bytes(b"NBT")
    (layout.state_dir / "brand_new_subsystem.json").write_text("[]")
    m = _capture(layout, at=datetime(2026, 1, 2, tzinfo=UTC))

    import tarfile

    with tarfile.open(layout.backup_dir / m.archive) as tar:
        names = set(tar.getnames())
    assert "data/worlds/Home/level.dat" in names
    assert "cobble-state/brand_new_subsystem.json" in names
    assert "data/server.properties" in names


def test_capture_stores_data_symlinks_as_symlinks(tmp_settings: Settings, tmp_path) -> None:
    layout = _layout_with_state(tmp_settings)
    (layout.data_dir / "bedrock_server").symlink_to("../current/bedrock_server")
    m = _capture(layout)
    import tarfile

    with tarfile.open(layout.backup_dir / m.archive) as tar:
        info = tar.getmember("data/bedrock_server")
    assert info.issym()
    assert info.linkname == "../current/bedrock_server"


# -- 3.6 verification ---------------------------------------------
def test_verify_accepts_a_good_archive_and_rejects_a_truncated_one(
    tmp_settings: Settings,
) -> None:
    layout = _layout_with_state(tmp_settings)
    m = _capture(layout)
    archive = layout.backup_dir / m.archive
    verify_archive(archive, m)  # no raise

    archive.write_bytes(archive.read_bytes()[: m.size_bytes // 2])
    with pytest.raises(BackupError):
        verify_archive(archive, m)


def test_verify_rejects_a_corrupt_body_with_matching_size(tmp_settings: Settings) -> None:
    layout = _layout_with_state(tmp_settings)
    m = _capture(layout)
    archive = layout.backup_dir / m.archive
    raw = bytearray(archive.read_bytes())
    raw[len(raw) // 2] ^= 0xFF  # flip a byte; size unchanged
    archive.write_bytes(raw)
    with pytest.raises(BackupError):
        verify_archive(archive, m)


# -- 3.5 atomicity ----------------------------------------------
def test_interrupted_capture_leaves_prior_backups_and_is_not_listed(
    tmp_settings: Settings, monkeypatch
) -> None:
    layout = _layout_with_state(tmp_settings)
    good = _capture(layout, at=datetime(2026, 1, 1, tzinfo=UTC))
    store = BackupStore(layout.backup_dir)
    assert [e.archive.name for e in store.list()] == [good.archive]

    # Make the sidecar write blow up *after* the archive is renamed into place.
    import cobble.backup.capture as capmod

    real_write = Manifest.write_atomic

    def boom(self, sidecar):
        raise OSError("disk full while writing sidecar")

    monkeypatch.setattr(capmod.Manifest, "write_atomic", boom)
    with pytest.raises(OSError):
        _capture(layout, at=datetime(2026, 1, 2, tzinfo=UTC))
    monkeypatch.setattr(capmod.Manifest, "write_atomic", real_write)

    # The interrupted capture left nothing the store will offer, and the prior
    # backup is intact.
    names = [e.archive.name for e in store.list()]
    assert names == [good.archive]
    assert not list(layout.backup_dir.glob("*.partial"))


# -- 3.7 listing ------------------------------------------------
def test_listing_reports_fields_and_empty_destination_is_not_an_error(
    tmp_settings: Settings,
) -> None:
    layout = Layout.from_settings(tmp_settings)
    # destination does not exist yet
    missing = BackupStore(layout.backup_dir / "nope")
    assert missing.list() == []

    layout.ensure_directories()
    (layout.data_dir / "server.properties").write_text("x\n")
    m = _capture(layout, version="1.26.45.1", clean=False, at=datetime(2026, 3, 4, tzinfo=UTC))
    (entry,) = BackupStore(layout.backup_dir).list()
    assert entry.restorable is True
    assert entry.captured_at == m.captured_at
    assert entry.manifest.bedrock_version == "1.26.45.1"
    assert entry.manifest.shutdown_clean is False
    assert entry.size_bytes == m.size_bytes > 0
    d = entry.to_dict()
    assert d["archive"] == m.archive and d["restorable"] is True


def test_corrupt_backup_excluded_from_restorable_but_still_listed(
    tmp_settings: Settings,
) -> None:
    layout = _layout_with_state(tmp_settings)
    m = _capture(layout)
    (layout.backup_dir / m.archive).write_bytes(b"junk")
    (entry,) = BackupStore(layout.backup_dir).list()
    assert entry.restorable is False
    assert entry.reason
    assert BackupStore(layout.backup_dir).latest_restorable() is None


# -- 3.8 retention --------------------------------------------
def test_prune_keeps_newest_and_removes_oldest_beyond_limit(tmp_settings: Settings) -> None:
    layout = _layout_with_state(tmp_settings)
    made = [_capture(layout, at=datetime(2026, 1, day, tzinfo=UTC)).archive for day in range(1, 6)]
    store = BackupStore(layout.backup_dir)

    removed = store.prune(keep=2)
    kept = [e.archive.name for e in store.list()]
    assert made[-1] in kept and made[-2] in kept  # two newest kept
    assert set(removed) == set(made[:3])  # three oldest removed
    assert len(kept) == 2


def test_prune_never_removes_the_single_remaining_usable_backup(tmp_settings: Settings) -> None:
    layout = _layout_with_state(tmp_settings)
    only = _capture(layout).archive
    store = BackupStore(layout.backup_dir)
    assert store.prune(keep=0) == []
    assert [e.archive.name for e in store.list()] == [only]


def test_prune_protects_newest_usable_even_when_a_newer_one_is_corrupt(
    tmp_settings: Settings,
) -> None:
    layout = _layout_with_state(tmp_settings)
    old = _capture(layout, at=datetime(2026, 1, 1, tzinfo=UTC)).archive
    newer_bad = _capture(layout, at=datetime(2026, 1, 2, tzinfo=UTC)).archive
    (layout.backup_dir / newer_bad).write_bytes(b"junk")
    store = BackupStore(layout.backup_dir)

    store.prune(keep=1)
    names = [e.archive.name for e in store.list()]
    assert old in names  # the usable one survived
    # (the corrupt newer one may or may not be pruned; the usable one must stay)


def test_archive_is_gzip(tmp_settings: Settings) -> None:
    layout = _layout_with_state(tmp_settings)
    m = _capture(layout)
    with gzip.open(layout.backup_dir / m.archive) as fh:
        assert fh.read(1)  # decompresses
    assert sidecar_for(layout.backup_dir / m.archive).is_file()
