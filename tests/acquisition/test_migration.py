"""Section 4: one-time migration of an M1 installation to the data/ layout.

Tasks 4.1-4.5.
"""

from __future__ import annotations

import json
import os

import pytest

from cobble.acquisition.layout import Layout
from cobble.acquisition.migration import LayoutMigration, MigrationError
from cobble.backup.service import BackupService
from cobble.backup.store import BackupStore
from cobble.settings import Settings
from cobble.supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio


def _make_m1_installation(settings: Settings, version: str = "1.26.45.1") -> Layout:
    """Lay down a pre-separation installation: world + config inside the
    version directory, `current` pointing at it, no data/ separation."""
    layout = Layout.from_settings(settings)
    layout.ensure_directories()
    vdir = layout.version_dir(version)
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "bedrock_server").write_text("#!/bin/true\n")
    (vdir / "bedrock_server").chmod(0o755)
    (vdir / "definitions").mkdir()
    (vdir / "definitions" / "biomes.json").write_text("{}")
    (vdir / "server.properties").write_text("level-name=Home\nallow-list=true\n")
    (vdir / "permissions.json").write_text('["op"]')
    (vdir / "allowlist.json").write_text('["player"]')
    world = vdir / "worlds" / "Home"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_bytes(b"leveldb-manifest")
    (world / "level.dat").write_bytes(b"NBT-root")
    layout.set_active_version(version)
    return layout


def _migration(settings: Settings) -> tuple[LayoutMigration, Supervisor, Layout]:
    layout = Layout.from_settings(settings)
    sup = Supervisor(settings)
    backup = BackupService(settings, layout, sup)
    return LayoutMigration(settings, layout, sup, backup), sup, layout


# -- 4.1 detection -------------------------------------------------
async def test_detects_m1_layout_and_not_a_separated_one(tmp_settings: Settings) -> None:
    _make_m1_installation(tmp_settings)
    mig, _sup, layout = _migration(tmp_settings)
    assert mig.needs_migration() is True

    # After a completed migration the marker suppresses further runs.
    (layout.state_dir / "layout_migration.json").write_text(json.dumps({"status": "migrated"}))
    assert mig.needs_migration() is False


async def test_fresh_install_needs_no_migration(
    tmp_settings: Settings, install_fake_bedrock
) -> None:
    # 4.5 a fresh install (data/ layout, no world in the version dir) migrates nothing.
    install_fake_bedrock("1.99.0.1")
    mig, _sup, _layout = _migration(tmp_settings)
    assert mig.needs_migration() is False
    outcome = await mig.run()
    assert outcome.migrated is False
    assert mig._status() == "fresh"


# -- 4.2 backup-first --------------------------------------------
async def test_backup_failure_aborts_with_nothing_moved(tmp_settings: Settings) -> None:
    layout = _make_m1_installation(tmp_settings)
    # backup destination is unavailable (parent is a plain file)
    (tmp_settings.bedrock_root / "not-a-mount").write_text("file where a dir should be")
    bad = tmp_settings.model_copy(
        update={"backup_dir": tmp_settings.bedrock_root / "not-a-mount" / "sub"}
    )
    mig, _sup, _layout = _migration(bad)

    outcome = await mig.run()
    assert outcome.migrated is False
    assert "backup failed" in outcome.reason
    # nothing moved
    vdir = layout.version_dir("1.26.45.1")
    assert (vdir / "worlds" / "Home" / "level.dat").is_file()
    assert not (layout.data_dir / "worlds" / "Home").exists()
    assert mig._status() is None  # not marked done


# -- 4.3 the move ------------------------------------------------
async def test_migration_relocates_world_and_config_and_creates_symlinks(
    tmp_settings: Settings,
) -> None:
    layout = _make_m1_installation(tmp_settings)
    mig, sup, _layout = _migration(tmp_settings)

    outcome = await mig.run()
    assert outcome.migrated is True

    vdir = layout.version_dir("1.26.45.1")
    # world + config now under data/, gone from the version dir
    assert (layout.data_dir / "worlds" / "Home" / "level.dat").read_bytes() == b"NBT-root"
    assert (layout.data_dir / "worlds" / "Home" / "db" / "CURRENT").is_file()
    assert not (vdir / "worlds").exists()
    assert (
        layout.data_dir / "server.properties"
    ).read_text() == "level-name=Home\nallow-list=true\n"
    assert not (vdir / "server.properties").exists()
    # payload symlinks laid out and resolving to the active version
    link = layout.data_dir / "definitions"
    assert link.is_symlink()
    assert (link / "biomes.json").resolve() == (vdir / "definitions" / "biomes.json").resolve()
    # a verified backup of the pre-migration state exists
    (entry,) = BackupStore(layout.backup_dir).list()
    assert entry.restorable is True
    # server would start against the separated layout
    assert sup._layout.has_installation()
    assert layout.run_binary.resolve() == (vdir / "bedrock_server").resolve()


# -- 4.4 idempotent + resumable --------------------------------
async def test_migration_runs_once(tmp_settings: Settings) -> None:
    _make_m1_installation(tmp_settings)
    mig, _sup, _layout = _migration(tmp_settings)
    first = await mig.run()
    assert first.migrated is True

    n_backups = len(BackupStore(_layout.backup_dir).list())
    second = await mig.run()
    assert second.migrated is False
    assert mig.needs_migration() is False
    assert len(BackupStore(_layout.backup_dir).list()) == n_backups  # no second backup


async def test_interrupted_migration_completes_on_next_start_without_data_loss(
    tmp_settings: Settings,
) -> None:
    layout = _make_m1_installation(tmp_settings)
    vdir = layout.version_dir("1.26.45.1")

    # Simulate a crash after the "migrating" marker and after the world moved,
    # but before the config files were relocated.
    (layout.state_dir / "layout_migration.json").write_text(json.dumps({"status": "migrating"}))
    os.replace(vdir / "worlds", layout.data_dir / "worlds_tmp")
    # merge the moved world into data/worlds (pre-existing empty dir)
    for child in (layout.data_dir / "worlds_tmp").iterdir():
        os.replace(child, layout.data_dir / "worlds" / child.name)
    (layout.data_dir / "worlds_tmp").rmdir()
    assert not (vdir / "worlds").exists()
    assert (vdir / "server.properties").is_file()  # config not yet moved

    mig, _sup, _layout = _migration(tmp_settings)
    assert mig.needs_migration() is True  # marker == "migrating"
    outcome = await mig.run()
    assert outcome.migrated is True

    assert (layout.data_dir / "worlds" / "Home" / "level.dat").read_bytes() == b"NBT-root"
    assert (layout.data_dir / "server.properties").is_file()
    assert not (vdir / "server.properties").exists()
    # a resume takes no fresh backup
    assert BackupStore(layout.backup_dir).list() == []


async def test_migration_requires_the_server_stopped(
    tmp_settings: Settings, make_supervisor
) -> None:
    _make_m1_installation(tmp_settings)
    layout = Layout.from_settings(tmp_settings)
    # a supervisor whose state we force to RUNNING-ish is awkward; instead assert
    # the guard via a running fake server sharing the same settings.
    sup: Supervisor = make_supervisor("1.26.45.1", shutdown_timeout=5.0)
    await sup.start()
    backup = BackupService(sup._settings, layout, sup)
    mig = LayoutMigration(sup._settings, layout, sup, backup)
    with pytest.raises(MigrationError):
        await mig.run()
    await sup.stop()


# -- section 11: docs match reality --------------------------
async def test_fresh_install_layout_matches_the_documented_layout(
    tmp_settings: Settings, fake_vendor
) -> None:
    # 11.2 a bootstrap from nothing produces exactly the data/ layout the README
    # describes.
    from cobble.acquisition.bootstrap import bootstrap_if_needed

    s = tmp_settings.model_copy(update={"download_links_url": fake_vendor.links_url})
    bootstrap_if_needed(s)
    layout = Layout.from_settings(s)
    vdir = layout.version_dir(fake_vendor.version)

    for name in ("server.properties", "allowlist.json", "permissions.json"):
        p = layout.data_dir / name
        assert p.is_file() and not p.is_symlink(), name
    assert (layout.data_dir / "worlds").is_dir() and not (layout.data_dir / "worlds").is_symlink()
    assert (layout.data_dir / "bedrock_server").is_symlink()
    assert os.readlink(layout.data_dir / "bedrock_server") == os.path.join(
        "..", "current", "bedrock_server"
    )
    assert not (vdir / "worlds").exists()  # version dir carries no world


async def test_documented_revert_restores_a_runnable_m1_installation(
    tmp_settings: Settings,
) -> None:
    # 11.3 following the README's revert steps returns an M1-shaped installation.
    layout = _make_m1_installation(tmp_settings)
    mig, _sup, _layout = _migration(tmp_settings)
    assert (await mig.run()).migrated is True
    vdir = layout.version_dir("1.26.45.1")

    # --- the documented manual revert, with the server stopped ---
    import shutil

    active = layout.version_dir(layout.installed_version())
    os.replace(layout.data_dir / "worlds", active / "worlds")
    for name in ("server.properties", "allowlist.json", "permissions.json"):
        os.replace(layout.data_dir / name, active / name)
    shutil.rmtree(layout.data_dir)
    (layout.state_dir / "layout_migration.json").unlink()
    # -----------------------------------------------------------

    assert (vdir / "worlds" / "Home" / "level.dat").read_bytes() == b"NBT-root"
    assert (vdir / "server.properties").read_text() == "level-name=Home\nallow-list=true\n"
    assert layout.has_installation()  # M1 cobble could start this
    # and an M2 cobble would see it as needing migration again
    mig2, _s2, _l2 = _migration(tmp_settings)
    assert mig2.needs_migration() is True
