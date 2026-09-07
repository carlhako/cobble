"""Section 3 (orchestration half): cold capture, manifest cleanliness,
destination-failure handling.

Tasks 3.3, 3.4, 3.9, 3.10.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from cobble.acquisition.layout import Layout
from cobble.backup.service import BackupConflictError, BackupService
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

pytestmark = pytest.mark.asyncio


def _service(sup: Supervisor) -> BackupService:
    layout = Layout.from_settings(sup._settings)
    return BackupService(sup._settings, layout, sup)


async def test_cold_capture_from_running_ends_running(make_supervisor) -> None:
    # 3.3 a capture from running stops the server cleanly, then restarts it.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    svc = _service(sup)

    outcome = await svc.capture(reason="manual")

    assert outcome.ok is True
    assert sup.state is RunState.RUNNING  # returned to prior state
    assert sup.last_shutdown is not None and sup.last_shutdown.clean is True  # clean path
    assert sup.maintenance is None
    (entry,) = svc.list_backups()
    assert entry.restorable is True
    await sup.stop()


async def test_cold_capture_from_stopped_ends_stopped(make_supervisor) -> None:
    # 3.3 a capture from stopped does not start the server.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc = _service(sup)
    assert sup.state is RunState.STOPPED

    outcome = await svc.capture(reason="scheduled")

    assert outcome.ok is True
    assert sup.state is RunState.STOPPED
    assert len(svc.list_backups()) == 1


async def test_manifest_records_unclean_shutdown_of_the_captures_own_stop(
    make_supervisor,
) -> None:
    # 3.4 a capture whose stop needed SIGKILL is marked unclean in its manifest.
    sup: Supervisor = make_supervisor(shutdown_timeout=1.0)
    os.environ["FAKE_BDS_IGNORE_STOP"] = "1"
    try:
        await sup.start()
        svc = _service(sup)
        outcome = await svc.capture(reason="manual")
    finally:
        os.environ.pop("FAKE_BDS_IGNORE_STOP", None)

    assert outcome.ok is True
    (entry,) = svc.list_backups()
    assert entry.manifest.shutdown_clean is False
    await sup.stop()


async def test_unwritable_destination_records_unhealthy_and_leaves_server_running(
    make_supervisor,
) -> None:
    # 3.9 the server keeps running and the condition is retrievable.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    await sup.start()
    base_layout = Layout.from_settings(sup._settings)
    # Point the backup dir at a location whose parent denies writes.
    ro = base_layout.backup_dir / "ro"
    ro.mkdir()
    os.chmod(ro, 0o500)
    bad_settings = sup._settings.model_copy(update={"backup_dir": ro / "sub"})
    svc = BackupService(bad_settings, Layout.from_settings(bad_settings), sup)

    try:
        outcome = await svc.capture(reason="scheduled")
        assert outcome.ok is False
        assert svc.health is not None and "writable" in svc.health
        assert sup.state is RunState.RUNNING  # never stopped
        assert sup.maintenance is None

        # 3.10 a second failed attempt still runs; the schedule is not disabled.
        outcome2 = await svc.capture(reason="scheduled")
        assert outcome2.ok is False
        assert svc.health is not None
    finally:
        os.chmod(ro, 0o700)
        await sup.stop()


async def test_absent_destination_is_surfaced_without_raising(make_supervisor) -> None:
    # 3.9 an absent destination is reported, not raised.
    sup: Supervisor = make_supervisor()
    base_layout = Layout.from_settings(sup._settings)
    # A mount that is not there: model it as a path whose parent is a plain file,
    # so mkdir(parents=True) fails.
    stub = base_layout.bedrock_root / "missing-mount"
    stub.write_text("not a dir")
    bad_settings = sup._settings.model_copy(update={"backup_dir": stub / "sub"})
    svc = BackupService(bad_settings, Layout.from_settings(bad_settings), sup)

    outcome = await svc.capture(reason="manual")
    assert outcome.ok is False
    assert svc.health is not None


async def test_second_capture_while_one_in_progress_is_rejected(make_supervisor) -> None:
    # server-backups: request made while a backup is in progress fails with a
    # distinguishable error.
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc = _service(sup)

    slow = asyncio.Event()

    async def _slow_capture(reason: str):
        await slow.wait()
        return None

    svc._capture = _slow_capture  # type: ignore[assignment]

    first = asyncio.create_task(svc.capture(reason="manual"))
    await asyncio.sleep(0.05)  # let first set _busy
    assert svc.in_progress == "backup"
    with pytest.raises(BackupConflictError) as ei:
        await svc.capture(reason="manual")
    assert ei.value.code == "backup_in_progress"
    slow.set()
    await first
    assert svc.in_progress is None
