"""Section 5: restore of a captured backup over the live installation.

Tasks 5.1-5.4.
"""

from __future__ import annotations

import json
import os

import pytest

import cobble.backup.service as service_mod
from cobble.acquisition.layout import Layout
from cobble.backup.service import BackupService
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

    assert outcome.ok is True
    assert sup.state is RunState.RUNNING
    assert sup.maintenance is None
    await sup.stop()


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

    monkeypatch.setattr(service_mod, "_extract_over_layout", boom)
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
    assert restored == ["Family World"]


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
