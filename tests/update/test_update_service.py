"""Section 6: the update state machine (tasks 6.1-6.14)."""

from __future__ import annotations

import os
import stat
import sys

import pytest

import cobble.update.service as service_mod
from cobble.acquisition.installer import InstallError
from cobble.acquisition.layout import Layout
from cobble.acquisition.version_source import ResolvedVersion
from cobble.backup.service import BackupService
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor
from cobble.update.records import UpdateStateStore
from cobble.update.service import UpdateConflictError, UpdateService

pytestmark = pytest.mark.asyncio

FAKE_BEDROCK = __import__("pathlib").Path(__file__).parents[1] / "supervisor" / "fake_bedrock.py"

_GOOD = f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_BEDROCK}" "$@"\n'
# `exec` so a SIGKILL closes the stdout pipe immediately (no orphan holding it).
_NEVER_READY = '#!/bin/sh\necho "[INFO] Starting Server"\nexec sleep 20\n'
# ready, then dirties the world and exits inside the grace window
_DIES_IN_GRACE = (
    '#!/bin/sh\necho "[INFO] Starting Server"\necho "[INFO] Server started."\n'
    "echo dirty > worlds/W/marker\nsleep 0.4\nexit 1\n"
)


def _write_binary(vdir, script: str) -> None:
    vdir.mkdir(parents=True, exist_ok=True)
    b = vdir / "bedrock_server"
    b.write_text(script)
    b.chmod(b.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _installer(new_script: str):
    def _fake_install(resolved: ResolvedVersion, layout: Layout, settings) -> None:
        assert layout.installed_version() != resolved.version  # not yet active
        _write_binary(layout.version_dir(resolved.version), new_script)

    return _fake_install


def _service(sup: Supervisor, *, available: str = "2.0.0.1", grace: float = 1.0) -> UpdateService:
    sup._settings = sup._settings.model_copy(update={"update_grace_seconds": grace})
    layout = Layout.from_settings(sup._settings)
    backup = BackupService(sup._settings, layout, sup)
    return UpdateService(
        sup._settings,
        layout,
        sup,
        backup,
        resolver=lambda _s: ResolvedVersion(available, "http://vendor/x.zip"),
    )


@pytest.fixture(autouse=True)
def _patch_installer(monkeypatch):
    """Route install_version through whatever the current test's service set."""
    holder = {}

    def dispatch(resolved, layout, settings):
        return holder["fn"](resolved, layout, settings)

    monkeypatch.setattr(service_mod, "install_version", dispatch)
    return holder


def _use_installer(patch_holder, fn) -> None:
    patch_holder["fn"] = fn


def _seed_world(layout: Layout, marker: bytes) -> None:
    (layout.data_dir / "worlds" / "W").mkdir(parents=True, exist_ok=True)
    (layout.data_dir / "worlds" / "W" / "marker").write_bytes(marker)


# -- 6.1 availability + unreachable ---------------------------------
async def test_unreachable_vendor_is_surfaced_without_raising_or_updating(
    make_supervisor, _patch_installer
):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    await sup.start()
    layout = Layout.from_settings(sup._settings)
    svc = UpdateService(
        sup._settings,
        layout,
        sup,
        BackupService(sup._settings, layout, sup),
        resolver=lambda _s: None,
    )
    check = await svc.check()
    assert check.error is not None and check.available is None
    result = await svc.apply(reason="scheduled")
    assert result.ok is False and result.status == "aborted"
    assert sup.state is RunState.RUNNING  # untouched
    await sup.stop()


async def test_up_to_date_attempts_no_update(make_supervisor):
    sup: Supervisor = make_supervisor("2.0.0.1", shutdown_timeout=5.0)
    await sup.start()
    layout = Layout.from_settings(sup._settings)
    svc = UpdateService(
        sup._settings,
        layout,
        sup,
        BackupService(sup._settings, layout, sup),
        resolver=lambda _s: ResolvedVersion("2.0.0.1", "http://v/x.zip"),
    )
    check = await svc.check()
    assert check.up_to_date is True
    result = await svc.apply()
    assert result.status == "up_to_date"
    assert sup.maintenance is None and sup.state is RunState.RUNNING
    await sup.stop()


# -- 6.2 acquisition while running --------------------------------
async def test_failed_acquisition_leaves_server_running_and_version_unchanged(
    make_supervisor, _patch_installer
):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    await sup.start()
    svc = _service(sup)

    def boom(resolved, layout, settings):
        assert sup.state is RunState.RUNNING  # 6.2 not stopped during acquisition
        raise InstallError("download stalled")

    _use_installer(_patch_installer, boom)
    result = await svc.apply(reason="scheduled")
    assert result.status == "aborted" and result.to_version == "2.0.0.1"
    assert sup.state is RunState.RUNNING
    assert sup.installed_version() == "1.0.0.1"
    await sup.stop()


# -- 6.3 unclean shutdown --------------------------------------
async def test_unclean_pre_update_shutdown_abandons_before_activation(
    make_supervisor, _patch_installer
):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=1.0)
    svc = _service(sup)
    _use_installer(_patch_installer, _installer(_GOOD))
    os.environ["FAKE_BDS_IGNORE_STOP"] = "1"
    try:
        await sup.start()
        result = await svc.apply(reason="scheduled")
    finally:
        os.environ.pop("FAKE_BDS_IGNORE_STOP", None)
    assert result.status == "aborted" and result.step == "stop"
    assert sup.installed_version() == "1.0.0.1"  # active version unchanged
    assert sup.state is RunState.RUNNING  # previous version restarted
    await sup.stop()


# -- 6.4 pre-update backup fails ------------------------------
async def test_unverifiable_pre_update_backup_abandons_update(make_supervisor, _patch_installer):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    # backup destination unavailable
    (sup._settings.bedrock_root / "no-mount").write_text("x")
    bad = sup._settings.model_copy(
        update={"backup_dir": sup._settings.bedrock_root / "no-mount" / "d"}
    )
    layout = Layout.from_settings(bad)
    svc = UpdateService(
        bad,
        layout,
        sup,
        BackupService(bad, layout, sup),
        resolver=lambda _s: ResolvedVersion("2.0.0.1", "http://v/x.zip"),
    )
    _use_installer(_patch_installer, _installer(_GOOD))
    await sup.start()
    result = await svc.apply(reason="scheduled")
    assert result.status == "aborted" and result.step == "backup"
    assert sup.installed_version() == "1.0.0.1"
    assert sup.state is RunState.RUNNING
    await sup.stop()


# -- 6.5 / 6.7 / 6.8 readiness failure -> rollback --------------
async def test_new_version_never_ready_rolls_back_to_previous(make_supervisor, _patch_installer):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0, readiness_timeout=1.0)
    layout = Layout.from_settings(sup._settings)
    _seed_world(layout, b"pre-update")
    svc = _service(sup)
    _use_installer(_patch_installer, _installer(_NEVER_READY))
    await sup.start()

    result = await svc.apply(reason="scheduled")

    assert result.status == "rolled_back" and result.rolled_back is True
    assert result.from_version == "2.0.0.1" and result.to_version == "1.0.0.1"
    assert sup.installed_version() == "1.0.0.1"  # previous reactivated
    assert sup.state is RunState.RUNNING  # rollback restored service, no operator action
    assert (layout.data_dir / "worlds" / "W" / "marker").read_bytes() == b"pre-update"
    await sup.stop()


async def test_new_version_dies_in_grace_window_rolls_back_and_restores_world(
    make_supervisor, _patch_installer
):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    settings = sup._settings.model_copy(update={"update_grace_seconds": 2.0})
    sup._settings = settings
    layout = Layout.from_settings(settings)
    _seed_world(layout, b"pre-update")
    svc = UpdateService(
        settings,
        layout,
        sup,
        BackupService(settings, layout, sup),
        resolver=lambda _s: ResolvedVersion("2.0.0.1", "http://v/x.zip"),
    )
    _use_installer(_patch_installer, _installer(_DIES_IN_GRACE))
    await sup.start()

    result = await svc.apply(reason="scheduled")

    assert result.status == "rolled_back"
    assert result.step == "grace-window" or "grace" in result.detail
    assert sup.installed_version() == "1.0.0.1"
    # 6.8 world left dirty by the failed version is not retained
    assert (layout.data_dir / "worlds" / "W" / "marker").read_bytes() == b"pre-update"
    await sup.stop()


# -- 6.9 terminal ---------------------------------------------
async def test_rollback_that_cannot_start_previous_is_terminal(make_supervisor, _patch_installer):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0, readiness_timeout=1.0)
    svc = _service(sup)

    def install_broken_new_and_break_previous(resolved, layout, settings):
        _write_binary(layout.version_dir(resolved.version), _NEVER_READY)
        # sabotage the previous version so the rollback cannot start it
        _write_binary(layout.version_dir("1.0.0.1"), _NEVER_READY)

    _use_installer(_patch_installer, install_broken_new_and_break_previous)
    await sup.start()

    result = await svc.apply(reason="scheduled")
    assert result.status == "terminal" and result.terminal is True
    assert svc.terminal is True

    # 6.9 no further automatic action
    again = await svc.apply(reason="scheduled")
    assert again.status == "terminal"


# -- 6.10 / 6.11 quarantine ---------------------------------
async def test_failed_version_is_quarantined_then_clearable(make_supervisor, _patch_installer):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0, readiness_timeout=1.0)
    svc = _service(sup)
    _use_installer(_patch_installer, _installer(_NEVER_READY))
    await sup.start()
    first = await svc.apply(reason="scheduled")
    assert first.status == "rolled_back"

    # 6.10 same version is no longer retried automatically
    check = await svc.check()
    assert check.skipped is True and "2.0.0.1" in check.skipped_reason
    skipped = await svc.apply(reason="scheduled")
    assert skipped.status == "skipped"

    # 6.11 a different vendor version is attempted normally
    svc._resolve = lambda _s: ResolvedVersion("3.0.0.1", "http://v/x.zip")
    _use_installer(_patch_installer, _installer(_GOOD))
    ok = await svc.apply(reason="scheduled")
    assert ok.status == "success" and ok.to_version == "3.0.0.1"

    # 6.11 an operator can clear the record
    svc._resolve = lambda _s: ResolvedVersion("2.0.0.1", "http://v/x.zip")
    # (2.0.0.1 is now older than the installed 3.0.0.1, so it reports up_to_date)
    svc.clear_failed("2.0.0.1")
    assert svc._store.is_failed("2.0.0.1") is False
    await sup.stop()


# -- 6.12 diagnostics survive restart ------------------------
async def test_failure_diagnostics_survive_a_cobble_restart(make_supervisor, _patch_installer):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0, readiness_timeout=1.0)
    svc = _service(sup)
    _use_installer(_patch_installer, _installer(_NEVER_READY))
    await sup.start()
    await svc.apply(reason="scheduled")
    await sup.stop()

    # a fresh store over the same state dir == a cobble restart
    reloaded = UpdateStateStore(sup._settings.state_dir / "updates.json")
    assert "2.0.0.1" in reloaded.failed_versions
    fv = reloaded.failed_versions["2.0.0.1"]
    assert fv.step in ("readiness", "grace-window")
    assert reloaded.last_result is not None
    assert reloaded.last_result.output_tail  # captured server output retained


# -- 6.13 version pruning ----------------------------------
async def test_successful_update_prunes_older_versions_but_keeps_rollback_source(
    make_supervisor, _patch_installer
):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    layout = Layout.from_settings(sup._settings)
    _write_binary(layout.version_dir("0.9.0.1"), _GOOD)  # an older install
    svc = _service(sup)
    _use_installer(_patch_installer, _installer(_GOOD))
    await sup.start()

    result = await svc.apply(reason="scheduled")
    assert result.status == "success"
    present = set(layout.installed_versions())
    assert "2.0.0.1" in present and "1.0.0.1" in present  # new + rollback source
    assert "0.9.0.1" not in present  # older than the rollback source, pruned
    await sup.stop()


# -- 6.14 concurrent guard --------------------------------
async def test_second_update_while_one_in_progress_is_rejected(make_supervisor, _patch_installer):
    sup: Supervisor = make_supervisor("1.0.0.1", shutdown_timeout=5.0)
    svc = _service(sup)
    import asyncio

    async def _slow_apply(reason):
        await asyncio.sleep(0.3)
        return None

    svc._apply = _slow_apply
    _use_installer(_patch_installer, _installer(_GOOD))
    first = asyncio.create_task(svc.apply(reason="manual"))
    await asyncio.sleep(0.05)
    with pytest.raises(UpdateConflictError) as ei:
        await svc.apply(reason="manual")
    assert ei.value.code == "update_in_progress"
    await first
    assert svc.in_progress is None
