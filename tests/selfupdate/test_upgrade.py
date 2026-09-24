"""cobble-self-update 3.1-3.5: requesting, following, and reporting an upgrade."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from cobble.acquisition.layout import Layout
from cobble.backup.service import BackupOutcome, BackupService
from cobble.selfupdate import upgrade as upgrade_mod
from cobble.selfupdate.release_check import ReleaseChecker
from cobble.selfupdate.upgrade import OPERATION, UpgradeError, UpgradeService, manual_command
from cobble.settings import Settings
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor


def _checker(settings: Settings, tag: str | None = "v0.5.0") -> ReleaseChecker:
    def handle(_req: httpx.Request) -> httpx.Response:
        if tag is None:
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "tag_name": tag,
                "html_url": f"https://github.com/carlhako/cobble/releases/tag/{tag}",
            },
        )

    c = ReleaseChecker(
        settings.model_copy(update={"release_api_url": "https://api.test"}),
        current="0.4.0",
        transport=httpx.MockTransport(handle),
    )
    c.check_now()
    return c


def _install_helper(settings: Settings) -> None:
    settings.upgrade_helper_path.parent.mkdir(parents=True, exist_ok=True)
    settings.upgrade_helper_path.write_text("#!/usr/bin/python3\n")
    settings.upgrade_status_dir.mkdir(parents=True, exist_ok=True)


def _write_status(settings: Settings, **fields) -> None:
    """Write the helper's status. Like the real helper, it echoes the outstanding
    request's id unless the test says otherwise."""
    if "request_id" not in fields:
        pending_file = settings.state_dir / "upgrade_pending.json"
        pending = json.loads(pending_file.read_text()) if pending_file.exists() else {}
        fields["request_id"] = pending.get("request_id")
    (settings.upgrade_status_dir / "status.json").write_text(json.dumps(fields))


def _desired_running(settings: Settings) -> bool:
    return json.loads(settings.runtime_state_file.read_text())["desired_running"]


@pytest.fixture
def sup(make_supervisor) -> Supervisor:
    return make_supervisor("1.0.0.1", shutdown_timeout=5.0, upgrade_timeout_seconds=30.0)


def _service(
    sup: Supervisor, *, tag: str | None = "v0.5.0", helper: bool = True, current: str = "0.4.0"
) -> UpgradeService:
    settings = sup._settings
    if helper:
        _install_helper(settings)
    backup = BackupService(settings, Layout.from_settings(settings), sup)
    return UpgradeService(
        settings, sup, backup, _checker(settings, tag), current=current, poll_seconds=0.01
    )


async def _wait_for(pred, limit: float = 10.0) -> None:
    # Polls file and supervisor state that has no event to await.
    async with asyncio.timeout(limit):
        while not pred():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


# -- 3.1 helper detection -------------------------------------------------------
async def test_helper_detection(sup: Supervisor) -> None:
    svc = _service(sup, helper=False)
    assert svc.helper_installed() is False
    _install_helper(sup._settings)
    assert svc.helper_installed() is True
    # Both halves are needed: the script and the root-owned status directory.
    sup._settings.upgrade_status_dir.rmdir()
    assert svc.helper_installed() is False


async def test_manual_command_names_the_configured_repo(sup: Supervisor) -> None:
    assert manual_command(sup._settings) == (
        "curl -fsSL https://github.com/carlhako/cobble/releases/latest/download/install.sh | bash"
    )


# -- 3.2 the maintenance operation ---------------------------------------------
async def test_request_backs_up_then_writes_the_request_with_the_server_stopped(
    sup: Supervisor,
) -> None:
    await sup.start()
    svc = _service(sup)
    order: list[str] = []
    real_snapshot = svc._backup.snapshot_now

    async def snapshot(reason: str) -> BackupOutcome:
        assert not svc.request_file.exists()
        order.append(f"backup:{reason}")
        return await real_snapshot(reason)

    svc._backup.snapshot_now = snapshot  # type: ignore[method-assign]

    view = await svc.request("0.5.0")

    assert order == ["backup:pre-upgrade"]
    req = json.loads(svc.request_file.read_text())
    pending = json.loads(svc.pending_file.read_text())
    assert req["tag"] == "v0.5.0"
    assert len(req["request_id"]) == 32 and req["request_id"] == pending["request_id"]
    assert pending["from"] == "0.4.0" and pending["to"] == "0.5.0" and pending["tag"] == "v0.5.0"
    assert view["state"] == "pending" and view["to"] == "0.5.0"
    assert sup.state is RunState.STOPPED
    assert sup.maintenance == OPERATION
    # The backup's stop cleared desired_running; the upgrade put it back.
    assert _desired_running(sup._settings) is True
    assert svc.in_progress()

    _write_status(sup._settings, tag="v0.5.0", state="failed", error="stop the test")
    await _wait_for(lambda: sup.maintenance is None)
    await sup.stop()


async def test_backup_failure_writes_no_request_and_restores_the_server(sup: Supervisor) -> None:
    await sup.start()
    svc = _service(sup)

    async def failing(reason: str) -> BackupOutcome:
        return BackupOutcome(ok=False, at="T", reason=reason, error="disk full")

    svc._backup.snapshot_now = failing  # type: ignore[method-assign]
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.5.0")
    assert exc.value.code == "backup_failed"
    assert not svc.request_file.exists()
    assert not svc.pending_file.exists()
    await _wait_for(lambda: sup.maintenance is None)
    assert sup.state is RunState.RUNNING
    last = svc.view()
    assert last["state"] == "failed" and "disk full" in last["error"]
    await sup.stop()


async def test_stopped_server_stays_intended_stopped(sup: Supervisor) -> None:
    await sup.start()
    await sup.stop()
    svc = _service(sup)
    await svc.request("0.5.0")
    assert _desired_running(sup._settings) is False
    _write_status(sup._settings, tag="v0.5.0", state="failed")
    await _wait_for(lambda: sup.maintenance is None)
    assert sup.state is RunState.STOPPED


# -- 3.3 refusals ----------------------------------------------------------------
async def test_refused_when_no_update_available(sup: Supervisor) -> None:
    svc = _service(sup, tag="v0.4.0")
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.4.0")
    assert exc.value.code == "no_update_available"


async def test_refused_when_availability_unknown(sup: Supervisor) -> None:
    svc = _service(sup, tag=None)
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.5.0")
    assert exc.value.code == "no_update_available"


async def test_refused_on_version_mismatch(sup: Supervisor) -> None:
    svc = _service(sup)
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.6.0")
    assert exc.value.code == "version_mismatch"
    assert not svc.request_file.exists()


async def test_refused_when_helper_not_installed(sup: Supervisor) -> None:
    svc = _service(sup, helper=False)
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.5.0")
    assert exc.value.code == "helper_not_installed"


async def test_refused_when_already_pending(sup: Supervisor) -> None:
    svc = _service(sup)
    svc.pending_file.write_text(json.dumps({"tag": "v0.5.0", "to": "0.5.0"}))
    with pytest.raises(UpgradeError) as exc:
        await svc.request("0.5.0")
    assert exc.value.code == "upgrade_in_progress"


async def test_refused_during_maintenance(sup: Supervisor) -> None:
    svc = _service(sup)
    async with sup.maintenance_scope("backing_up"):
        with pytest.raises(UpgradeError) as exc:
            await svc.request("0.5.0")
    assert exc.value.code == "maintenance_conflict"
    assert not svc.request_file.exists()


# -- 3.4 following the helper while this cobble is still running -----------------
@pytest.mark.parametrize("terminal", ["failed", "rejected"])
async def test_helper_failure_releases_maintenance_and_restarts(
    sup: Supervisor, terminal: str
) -> None:
    await sup.start()
    svc = _service(sup)
    await svc.request("0.5.0")
    _write_status(sup._settings, tag="v0.5.0", state="running")
    await _wait_for(lambda: (sup.maintenance_step or "").startswith("installing"))
    _write_status(
        sup._settings, tag="v0.5.0", state=terminal, error="bad digest", log_tail="tail..."
    )
    await _wait_for(lambda: sup.maintenance is None)
    assert sup.state is RunState.RUNNING
    last = svc.view()
    assert last["state"] == terminal
    assert last["error"] == "bad digest" and last["log_tail"] == "tail..."
    assert last["from"] == "0.4.0" and last["to"] == "0.5.0"
    assert not svc.pending_file.exists() and not svc.request_file.exists()
    await sup.stop()


async def test_status_for_another_tag_is_ignored(sup: Supervisor) -> None:
    svc = _service(sup)
    await svc.request("0.5.0")
    _write_status(sup._settings, tag="v0.3.0", state="failed", request_id="0" * 32)
    await asyncio.sleep(0.1)
    assert sup.maintenance == OPERATION
    _write_status(sup._settings, tag="v0.5.0", state="failed")
    await _wait_for(lambda: sup.maintenance is None)


async def test_earlier_attempt_at_the_same_tag_is_ignored(sup: Supervisor) -> None:
    # A retry after a failed attempt: status.json still holds that attempt's
    # outcome for the very same tag. It must not end this request's wait.
    _install_helper(sup._settings)
    _write_status(sup._settings, tag="v0.5.0", state="failed", error="old", request_id="0" * 32)
    svc = _service(sup)
    await svc.request("0.5.0")
    await asyncio.sleep(0.1)
    assert sup.maintenance == OPERATION
    assert svc.request_file.exists()
    assert svc.view()["state"] == "pending"
    _write_status(sup._settings, tag="v0.5.0", state="failed", error="new")
    await _wait_for(lambda: sup.maintenance is None)
    assert svc.view()["error"] == "new"


async def test_unexpected_error_after_the_stop_restores_the_server(sup: Supervisor) -> None:
    await sup.start()
    svc = _service(sup)

    async def exploding(reason: str) -> BackupOutcome:
        raise OSError("archive device vanished")

    svc._backup.snapshot_now = exploding  # type: ignore[method-assign]
    with pytest.raises(OSError):
        await svc.request("0.5.0")
    await _wait_for(lambda: sup.maintenance is None)
    assert sup.state is RunState.RUNNING
    assert not svc.pending_file.exists() and not svc.request_file.exists()
    assert not svc.in_progress()
    await sup.stop()


async def test_unexpected_error_after_the_hand_off_clears_the_pending_upgrade(
    sup: Supervisor, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sup.start()
    svc = _service(sup)

    async def exploding(*_args) -> None:
        raise RuntimeError("status unreadable")

    monkeypatch.setattr(svc, "_await_helper", exploding)
    await svc.request("0.5.0")
    await _wait_for(lambda: sup.maintenance is None)
    assert sup.state is RunState.RUNNING
    assert not svc.pending_file.exists() and not svc.request_file.exists()
    last = svc.view()
    assert last["state"] == "failed" and "status unreadable" in last["error"]
    await sup.stop()


async def test_timeout_gives_up_and_restarts(make_supervisor) -> None:
    sup = make_supervisor("1.0.0.1", shutdown_timeout=5.0, upgrade_timeout_seconds=0.3)
    await sup.start()
    svc = _service(sup)
    await svc.request("0.5.0")
    await _wait_for(lambda: sup.maintenance is None)
    assert sup.state is RunState.RUNNING
    last = svc.view()
    assert last["state"] == "failed" and "did not finish" in last["error"]
    assert not svc.request_file.exists()
    await sup.stop()


async def test_cancellation_leaves_the_pending_record(sup: Supervisor) -> None:
    # cobble being stopped by the helper's restart must not look like a failure.
    svc = _service(sup)
    await svc.request("0.5.0")
    await svc.stop()
    assert svc.pending_file.exists()
    assert svc.request_file.exists()
    assert not svc.last_file.exists()


# -- 3.5 reconciliation on the next start ---------------------------------------
def _seed_pending(settings: Settings, requested_at: str = "2999-01-01T00:00:00+00:00") -> None:
    (settings.state_dir / "upgrade_pending.json").write_text(
        json.dumps(
            {
                "from": "0.4.0",
                "to": "0.5.0",
                "tag": "v0.5.0",
                "request_id": "a" * 32,
                "requested_at": requested_at,
            }
        )
    )


async def test_startup_reports_success(sup: Supervisor) -> None:
    svc = _service(sup, current="0.5.0")
    _seed_pending(sup._settings)
    _write_status(sup._settings, tag="v0.5.0", state="succeeded", log_tail="ok")
    svc.start()
    await _wait_for(lambda: not svc.pending_file.exists())
    last = svc.view()
    assert last["state"] == "succeeded" and last["from"] == "0.4.0" and last["to"] == "0.5.0"
    assert last["error"] is None


async def test_startup_keeps_following_a_running_helper(sup: Supervisor) -> None:
    # The installer restarts cobble before the helper writes its final status.
    svc = _service(sup, current="0.5.0")
    _seed_pending(sup._settings)
    _write_status(sup._settings, tag="v0.5.0", state="running")
    svc.start()
    await asyncio.sleep(0.1)
    assert svc.view()["state"] == "running"
    _write_status(sup._settings, tag="v0.5.0", state="succeeded")
    await _wait_for(lambda: not svc.pending_file.exists())
    assert svc.view()["state"] == "succeeded"


async def test_startup_past_the_timeout_keeps_following_a_running_helper(
    sup: Supervisor,
) -> None:
    # A slow install: the new cobble starts after upgrade_timeout_seconds has
    # passed, and the helper only writes "succeeded" once cobble is healthy.
    svc = _service(sup, current="0.5.0")
    _seed_pending(sup._settings, requested_at="2000-01-01T00:00:00+00:00")
    _write_status(sup._settings, tag="v0.5.0", state="running")
    svc.start()
    await asyncio.sleep(0.1)
    assert svc.view()["state"] == "running"
    _write_status(sup._settings, tag="v0.5.0", state="succeeded")
    await _wait_for(lambda: not svc.pending_file.exists())
    assert svc.view()["state"] == "succeeded"


async def test_a_helper_stuck_running_is_given_up_after_the_grace(
    sup: Supervisor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(upgrade_mod, "FOLLOW_GRACE_SECONDS", 0.2)
    svc = _service(sup, current="0.5.0")
    _seed_pending(sup._settings, requested_at="2000-01-01T00:00:00+00:00")
    _write_status(sup._settings, tag="v0.5.0", state="running")
    svc.start()
    await _wait_for(lambda: not svc.pending_file.exists())
    last = svc.view()
    assert last["state"] == "failed" and "interrupted" in last["error"]


async def test_a_finished_helper_reads_as_running_until_concluded(sup: Supervisor) -> None:
    # Between the helper's final write and cobble's next poll, the upgrade must
    # not appear to fall back to "waiting for the helper".
    svc = _service(sup, current="0.5.1")
    _seed_pending(sup._settings)
    _write_status(sup._settings, tag="v0.5.0", state="succeeded")
    assert svc.view()["state"] == "running"


async def test_startup_reports_failure(sup: Supervisor) -> None:
    svc = _service(sup)
    _seed_pending(sup._settings)
    _write_status(sup._settings, tag="v0.5.0", state="failed", error="installer exited 1")
    svc.start()
    await _wait_for(lambda: not svc.pending_file.exists())
    last = svc.view()
    assert last["state"] == "failed" and last["error"] == "installer exited 1"


async def test_success_reported_but_old_version_running_is_a_failure(sup: Supervisor) -> None:
    svc = _service(sup, current="0.4.0")
    _seed_pending(sup._settings)
    _write_status(sup._settings, tag="v0.5.0", state="succeeded")
    svc.start()
    await _wait_for(lambda: not svc.pending_file.exists())
    assert svc.view()["state"] == "failed"


async def test_orphaned_request_is_reported_interrupted(sup: Supervisor) -> None:
    svc = _service(sup)
    _seed_pending(sup._settings, requested_at="2000-01-01T00:00:00+00:00")
    svc.processing_file.parent.mkdir(parents=True, exist_ok=True)
    svc.processing_file.write_text(json.dumps({"tag": "v0.5.0"}))
    svc.start()
    await _wait_for(lambda: not svc.pending_file.exists())
    last = svc.view()
    assert last["state"] == "failed" and "interrupted" in last["error"]


async def test_nothing_outstanding_starts_nothing(sup: Supervisor) -> None:
    svc = _service(sup)
    svc.start()
    assert svc._follow_task is None
    assert svc.view() is None


def test_paths_are_where_the_helper_expects(tmp_settings: Settings) -> None:
    svc = UpgradeService(tmp_settings, None, None, None)  # type: ignore[arg-type]
    assert svc.request_file == tmp_settings.state_dir / "upgrade" / "request.json"
    assert svc.processing_file == tmp_settings.state_dir / "upgrade" / "request.processing"
    assert svc.status_file == Path(tmp_settings.upgrade_status_dir) / "status.json"


async def test_tagless_rejection_after_the_request_ends_the_wait(sup: Supervisor) -> None:
    # The helper could not read a tag from a tampered request: it records
    # "rejected" with no tag. cobble must not wait out the full timeout.
    svc = _service(sup)
    await svc.request("0.5.0")
    _write_status(
        sup._settings,
        tag=None,
        state="rejected",
        finished_at="2999-01-01T00:00:00+00:00",
        request_id=None,
    )
    await _wait_for(lambda: sup.maintenance is None, limit=5.0)
    assert svc.view()["state"] == "rejected"


async def test_stale_tagless_rejection_is_ignored(sup: Supervisor) -> None:
    svc = _service(sup)
    _write_status(
        sup._settings,
        tag=None,
        state="rejected",
        finished_at="2000-01-01T00:00:00+00:00",
        request_id=None,
    )
    await svc.request("0.5.0")
    await asyncio.sleep(0.1)
    assert sup.maintenance == OPERATION
    _write_status(sup._settings, tag="v0.5.0", state="failed")
    await _wait_for(lambda: sup.maintenance is None)


def test_default_timeout_outlasts_the_helper_unit(tmp_settings: Settings) -> None:
    # cobble must not give up on a helper systemd still lets run.
    unit = Path(__file__).resolve().parents[2] / "deploy" / "cobble-upgrade.service"
    (line,) = [ln for ln in unit.read_text().splitlines() if ln.startswith("TimeoutStartSec=")]
    minutes = int(line.split("=", 1)[1].removesuffix("min"))
    assert Settings.model_fields["upgrade_timeout_seconds"].default > minutes * 60
