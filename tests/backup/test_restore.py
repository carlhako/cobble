"""Section 5: restore of a captured backup over the live installation.

Tasks 5.1-5.4.
"""

from __future__ import annotations

import json
import os

import pytest

import cobble.backup.service as service_mod
from cobble.acquisition.layout import Layout
from cobble.backup.pending import apply_pending_state, marker_path
from cobble.backup.service import BackupConflictError, BackupService
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio


def _service(sup: Supervisor) -> BackupService:
    return BackupService(sup._settings, Layout.from_settings(sup._settings), sup)


def _seed_world(layout: Layout, marker: bytes, props: str) -> None:
    world = layout.data_dir / "worlds" / "W"
    world.mkdir(parents=True, exist_ok=True)
    (world / "marker").write_bytes(marker)
    (layout.data_dir / "server.properties").write_text(props)


async def test_restore_puts_back_the_captured_world(make_supervisor) -> None:
    # 5.1 the world after restore matches the captured one; the state being
    # replaced is captured first.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)

    _seed_world(layout, b"v1", "level-name=A\n")
    captured = await svc.capture(reason="manual")
    assert captured.ok

    _seed_world(layout, b"v2", "level-name=B\n")
    (layout.data_dir / "worlds" / "W" / "extra").write_bytes(b"junk-added-after")

    outcome = await svc.restore(captured.archive)

    assert outcome.ok is True
    assert outcome.replaced_capture and outcome.replaced_capture != captured.archive
    assert (layout.data_dir / "worlds" / "W" / "marker").read_bytes() == b"v1"
    assert (layout.data_dir / "server.properties").read_text() == "level-name=A\n"
    assert not (layout.data_dir / "worlds" / "W" / "extra").exists()  # replaced wholesale
    # the pre-restore safety capture is itself a restorable backup
    names = {e.archive.name for e in svc.list_backups() if e.restorable}
    assert outcome.replaced_capture in names


async def test_restore_from_running_returns_to_running(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    _seed_world(layout, b"v1", "x\n")
    captured = await svc.capture(reason="manual")
    await sup.start()

    outcome = await svc.restore(captured.archive)

    # The server stays stopped: the restart cobble now performs brings it back,
    # because the staged restore records that it was running (design.md D5).
    assert outcome.ok is True
    assert outcome.restarting is True
    assert sup.state is not RunState.RUNNING
    assert sup.maintenance is None
    pending = apply_pending_state(layout.state_dir)
    assert pending is not None and pending.was_running is True
    assert json.loads((layout.state_dir / "runtime.json").read_text()) == {
        "desired_running": True
    }


async def test_restore_refused_when_server_cannot_stop_cleanly(make_supervisor) -> None:
    # 5.2 existing state is not replaced and the failure is reported.
    sup: Supervisor = make_supervisor(shutdown_timeout=1.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    _seed_world(layout, b"original", "orig\n")
    captured = await svc.capture(reason="manual")
    _seed_world(layout, b"changed", "changed\n")

    os.environ["FAKE_BDS_IGNORE_STOP"] = "1"
    try:
        await sup.start()
        outcome = await svc.restore(captured.archive)
    finally:
        os.environ.pop("FAKE_BDS_IGNORE_STOP", None)

    assert outcome.ok is False
    assert "cleanly" in outcome.error
    # nothing replaced
    assert (layout.data_dir / "worlds" / "W" / "marker").read_bytes() == b"changed"
    await sup.stop()


async def test_restore_of_older_backup_warns_then_proceeds_on_confirmation(
    make_supervisor,
) -> None:
    # 5.3 a warning is surfaced; the restore still proceeds when confirmed.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    _seed_world(layout, b"old-world", "old\n")
    captured = await svc.capture(reason="manual")

    # Make the backup look like it came from an older server version.
    sidecar = layout.backup_dir / (captured.archive + ".json")
    data = json.loads(sidecar.read_text())
    data["bedrock_version"] = "1.0.0.0"
    sidecar.write_text(json.dumps(data))

    _seed_world(layout, b"new-world", "new\n")

    warned = await svc.restore(captured.archive)
    assert warned.ok is False
    assert warned.needs_confirmation is True
    assert "older" in warned.warning
    assert (layout.data_dir / "worlds" / "W" / "marker").read_bytes() == b"new-world"  # untouched

    confirmed = await svc.restore(captured.archive, confirm_old_version=True)
    assert confirmed.ok is True
    assert (layout.data_dir / "worlds" / "W" / "marker").read_bytes() == b"old-world"


async def test_restore_that_fails_partway_keeps_the_replaced_state_recoverable(
    make_supervisor, monkeypatch
) -> None:
    # 5.4 the capture taken of the replaced state remains available.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    _seed_world(layout, b"snapshot", "snap\n")
    captured = await svc.capture(reason="manual")
    _seed_world(layout, b"current-state", "cur\n")

    def boom(archive, layout):
        raise OSError("simulated mid-restore failure")

    monkeypatch.setattr(service_mod, "_stage_restore", boom)
    outcome = await svc.restore(captured.archive)

    assert outcome.ok is False
    assert outcome.replaced_capture is not None
    entry = svc.store.get(outcome.replaced_capture)
    assert entry is not None and entry.restorable is True
    # and that safety capture holds the state as it was just before the restore
    monkeypatch.undo()
    recovered = await svc.restore(outcome.replaced_capture)
    assert recovered.ok is True
    assert (layout.data_dir / "worlds" / "W" / "marker").read_bytes() == b"current-state"


async def test_completed_restore_notifies_the_restored_world_name(make_supervisor) -> None:
    # 4.3 (gamerule-editing-and-defaults): a completed restore names the world it
    # replaced so the next readiness repairs rather than adopts.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    restored: list[str] = []
    svc = BackupService(
        sup._settings, layout, sup, on_restored=restored.append
    )
    _seed_world(layout, b"v1", "level-name=Family World\n")
    captured = await svc.capture(reason="manual")
    _seed_world(layout, b"v2", "level-name=Family World\n")

    outcome = await svc.restore(captured.archive)
    assert outcome.ok is True
    # The gamerule marker lives in cobble.db, which is staged: it is set after
    # the next start applies the staged state, not into the state being replaced.
    assert restored == []
    pending = apply_pending_state(layout.state_dir)
    assert pending is not None and pending.level_name == "Family World"


async def test_failed_restore_does_not_notify(make_supervisor) -> None:
    # 4.3: a restore that is refused writes no marker.
    sup: Supervisor = make_supervisor(shutdown_timeout=1.0)
    layout = Layout.from_settings(sup._settings)
    restored: list[str] = []
    svc = BackupService(sup._settings, layout, sup, on_restored=restored.append)
    _seed_world(layout, b"original", "level-name=W\n")
    captured = await svc.capture(reason="manual")
    _seed_world(layout, b"changed", "level-name=W\n")

    os.environ["FAKE_BDS_IGNORE_STOP"] = "1"
    try:
        await sup.start()
        outcome = await svc.restore(captured.archive)
    finally:
        os.environ.pop("FAKE_BDS_IGNORE_STOP", None)

    assert outcome.ok is False
    assert restored == []
    await sup.stop()


# -- import-backup-archive: deferred state swap (design.md D5, D6, D8) ------
async def test_live_state_is_untouched_until_the_staged_restore_is_applied(
    make_supervisor,
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    state = layout.state_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / "maintenance_settings.json").write_text('{"v": "captured"}')
    (state / "backup_history.json").write_text('["captured-history"]')
    _seed_world(layout, b"v1", "level-name=W\n")
    captured = await svc.capture(reason="manual")

    (state / "maintenance_settings.json").write_text('{"v": "live"}')
    (state / "backup_history.json").write_text('["live-history"]')
    (state / "added-later.json").write_text("{}")

    outcome = await svc.restore(captured.archive)
    assert outcome.ok is True
    assert (state / "maintenance_settings.json").read_text() == '{"v": "live"}'
    assert marker_path(state).is_file()

    pending = apply_pending_state(state)
    assert pending is not None and pending.error is None
    assert (state / "maintenance_settings.json").read_text() == '{"v": "captured"}'
    # Instance-local: the destination keeps its own backup history.
    assert (state / "backup_history.json").read_text() == '["live-history"]'
    assert not (state / "added-later.json").exists()
    assert not marker_path(state).exists()
    assert not (state / ".pending-state").exists()


async def test_a_restore_keeps_the_destinations_cobble_timezone(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    state = layout.state_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / "cobble_settings.json").write_text('{"timezone": "Europe/London"}')
    (state / "maintenance_settings.json").write_text('{"v": "captured"}')
    _seed_world(layout, b"v1", "level-name=W\n")
    captured = await svc.capture(reason="manual")

    (state / "cobble_settings.json").write_text('{"timezone": "Australia/Brisbane"}')
    (state / "maintenance_settings.json").write_text('{"v": "live"}')

    assert (await svc.restore(captured.archive)).ok is True
    pending = apply_pending_state(state)
    assert pending is not None and pending.error is None
    assert (state / "cobble_settings.json").read_text() == '{"timezone": "Australia/Brisbane"}'
    assert (state / "maintenance_settings.json").read_text() == '{"v": "captured"}'


async def test_no_backup_or_restore_runs_while_a_restart_is_pending(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    _seed_world(layout, b"v1", "x\n")
    captured = await svc.capture(reason="manual")
    assert (await svc.restore(captured.archive)).ok is True
    assert svc.restart_pending is True

    with pytest.raises(BackupConflictError):
        await svc.capture(reason="manual")
    with pytest.raises(BackupConflictError):
        await svc.restore(captured.archive)


async def test_a_failed_restore_stages_nothing_and_needs_no_restart(
    make_supervisor, monkeypatch
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    _seed_world(layout, b"v1", "x\n")
    captured = await svc.capture(reason="manual")
    await sup.start()

    def boom(archive, layout):
        raise OSError("simulated mid-restore failure")

    monkeypatch.setattr(service_mod, "_stage_restore", boom)
    outcome = await svc.restore(captured.archive)
    assert outcome.ok is False and outcome.restarting is False
    assert not marker_path(layout.state_dir).exists()
    assert svc.restart_pending is False
    assert sup.state is RunState.RUNNING  # returned in-process, as before
    await sup.stop()


async def test_a_capture_leaves_out_a_held_upload_and_a_staged_restore(make_supervisor) -> None:
    import tarfile

    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    svc = _service(sup)
    _seed_world(layout, b"v1", "x\n")
    state = layout.state_dir
    (state / "import-staging").mkdir(parents=True, exist_ok=True)
    (state / "import-staging" / "upload.archive").write_bytes(b"big upload")
    (state / ".pending-state").mkdir()
    (state / ".pending-state" / "x").write_text("x")
    (state / "keep.json").write_text("{}")

    captured = await svc.capture(reason="manual")
    with tarfile.open(layout.backup_dir / captured.archive) as tar:
        names = tar.getnames()
    assert "cobble-state/keep.json" in names
    assert not any("import-staging" in n or ".pending-state" in n for n in names)
