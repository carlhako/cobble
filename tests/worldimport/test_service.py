"""Sections 3 and 4: free-space preflight, the version gate, and the
stop / capture / replace / start import sequence."""

from __future__ import annotations

import os

import pytest

import cobble.worldimport.service as service_mod
from cobble.acquisition.layout import Layout
from cobble.backup.artifact import BackupError
from cobble.backup.service import BackupService
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import MaintenanceConflictError, Supervisor
from cobble.worldimport.service import ImportService, InsufficientSpaceError

from ._fixtures import build_zip, make_level_dat, reference_archive_bytes, world_members

pytestmark = pytest.mark.asyncio


def _make(sup: Supervisor, *, on_restored=None) -> tuple[ImportService, Layout]:
    layout = Layout.from_settings(sup._settings)
    backup = BackupService(sup._settings, layout, sup)
    svc = ImportService(sup._settings, layout, sup, backup, on_restored=on_restored)
    return svc, layout


def _seed_world(layout: Layout, level_name: str, marker: bytes) -> None:
    world = layout.data_dir / "worlds" / level_name
    world.mkdir(parents=True, exist_ok=True)
    (world / "marker").write_bytes(marker)
    (layout.data_dir / "server.properties").write_text(f"level-name={level_name}\n")


def _stage(svc: ImportService, prefix: str, *, version=(1, 99, 0, 1)) -> None:
    members = world_members(prefix, level_dat=make_level_dat(version=list(version)))
    members[f"{prefix}imported-marker"] = b"IMPORTED"
    _stage_bytes(svc, build_zip(members))


def _stage_bytes(svc: ImportService, data: bytes) -> None:
    with svc.slot.open_partial() as fh:
        fh.write(data)
    svc.slot.commit_partial()


# -- 3.1 upload-time free space ------------------------------------
async def test_upload_refused_when_no_room_for_the_archive(make_supervisor, monkeypatch) -> None:
    sup: Supervisor = make_supervisor()
    svc, _ = _make(sup)
    monkeypatch.setattr(svc, "_free_bytes", lambda: 1024)

    async def body():
        yield b"x" * 4096
        raise AssertionError("the body was read despite the refusal")

    with pytest.raises(InsufficientSpaceError):
        await svc.receive_upload(body(), declared_size=50_000_000)
    assert svc.slot.held() is None
    assert not svc.slot.partial_path.exists()


# -- 3.2 apply-time free space, before any stop --------------------
async def test_apply_refused_for_space_before_the_server_is_stopped(
    make_supervisor, monkeypatch
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc, layout = _make(sup)
    _seed_world(layout, "Bedrock level", b"orig")
    _stage(svc, "worlds/W/")
    await sup.start()

    stopped: list = []
    real_stop = sup.maintenance_stop

    async def spy_stop(**kw):
        stopped.append(kw)
        await real_stop(**kw)

    monkeypatch.setattr(sup, "maintenance_stop", spy_stop)
    monkeypatch.setattr(svc, "_free_bytes", lambda: 1)

    outcome = await svc.apply()
    assert outcome.ok is False
    assert "insufficient space" in outcome.error
    assert stopped == []
    assert sup.state is RunState.RUNNING
    await sup.stop()


# -- 3.3 the figures are reported --------------------------------
async def test_space_refusal_names_required_and_available(make_supervisor, monkeypatch) -> None:
    sup: Supervisor = make_supervisor()
    svc, _ = _make(sup)
    monkeypatch.setattr(svc, "_free_bytes", lambda: 5)
    try:
        svc.check_upload_space(999_000_000)
    except InsufficientSpaceError as exc:
        assert "needs" in str(exc) and "available" in str(exc)
        assert exc.required > exc.available
    else:  # pragma: no cover
        raise AssertionError("expected a refusal")


# -- 4.1 version gate: four cases ------------------------------
async def test_version_gate_all_four_cases(make_supervisor) -> None:
    sup: Supervisor = make_supervisor("1.99.0.1")
    svc, _ = _make(sup)

    def gate(v, confirm=False):
        return svc._version_gate(v, confirm, "now", "W")

    newer = gate("2.0.0.0")
    assert newer is not None and newer.ok is False and newer.needs_confirmation is False
    # not overridable
    still = gate("2.0.0.0", confirm=True)
    assert still is not None and still.ok is False and still.needs_confirmation is False

    older = gate("1.0.0.0")
    assert older is not None and older.needs_confirmation is True and "older" in older.warning
    assert gate("1.0.0.0", confirm=True) is None  # confirmed → proceeds

    assert gate("1.99.0.1") is None  # equal → proceeds
    assert gate(None) is None  # unknown → proceeds


# -- 4.2 ordering, and an unclean stop leaves the world untouched --
async def test_import_reports_stages_in_order(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc, layout = _make(sup)
    _seed_world(layout, "Bedrock level", b"orig")
    _stage(svc, "worlds/W/")

    steps: list[str] = []
    sup.subscribe_maintenance(lambda _op, st: steps.append(st) if st else None)

    await sup.start()
    outcome = await svc.apply()
    assert outcome.ok is True
    assert steps == [
        "stopping the server",
        "capturing the world being replaced",
        "putting the world in place",
        "starting the server",
    ]
    assert sup.state is RunState.RUNNING
    await sup.stop()


async def test_import_refused_when_server_cannot_stop_cleanly(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=1.0)
    svc, layout = _make(sup)
    _seed_world(layout, "Bedrock level", b"orig")
    _stage(svc, "worlds/W/")

    os.environ["FAKE_BDS_IGNORE_STOP"] = "1"
    try:
        await sup.start()
        outcome = await svc.apply()
    finally:
        os.environ.pop("FAKE_BDS_IGNORE_STOP", None)

    assert outcome.ok is False
    assert "cleanly" in outcome.error
    assert (layout.data_dir / "worlds" / "Bedrock level" / "marker").read_bytes() == b"orig"
    await sup.stop()


# -- 4.3 capture failure abandons before any file is removed -------
def _boom_verify(*a, **k):
    raise BackupError("simulated capture verification failure")


async def test_capture_failure_leaves_the_world_byte_identical(
    make_supervisor, monkeypatch
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc, layout = _make(sup)
    _seed_world(layout, "Bedrock level", b"orig-bytes")
    _stage(svc, "worlds/W/")
    monkeypatch.setattr(service_mod, "verify_archive", _boom_verify)

    await sup.start()
    outcome = await svc.apply()
    assert outcome.ok is False
    assert "safety copy" in outcome.error
    assert (layout.data_dir / "worlds" / "Bedrock level" / "marker").read_bytes() == b"orig-bytes"
    assert not (layout.data_dir / "worlds" / "Bedrock level" / "imported-marker").exists()
    assert sup.state is RunState.RUNNING
    await sup.stop()


# -- 4.4 only the world subtree is extracted; levelname.txt rewritten
async def test_extracts_only_the_world_and_rewrites_levelname(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc, layout = _make(sup)
    _seed_world(layout, "MyWorld", b"orig")
    _stage_bytes(svc, reference_archive_bytes())

    await sup.start()
    outcome = await svc.apply(confirm_old_version=True)
    assert outcome.ok is True, outcome.error

    dest = layout.data_dir / "worlds" / "MyWorld"
    assert (dest / "levelname.txt").read_text() == "MyWorld"
    assert (dest / "db" / "CURRENT").is_file()
    assert not (dest / "bedrock_server").exists()
    assert not (dest / "worlds").exists()  # the enclosing prefix was stripped
    await sup.stop()


# -- 4.5 level-name unwritten; other worlds and server.properties untouched
async def test_other_worlds_and_config_untouched(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc, layout = _make(sup)
    _seed_world(layout, "Bedrock level", b"orig")
    for other in ("OtherA", "OtherB"):
        d = layout.data_dir / "worlds" / other
        d.mkdir(parents=True)
        (d / "keep").write_bytes(other.encode())
    props_before = (layout.data_dir / "server.properties").read_bytes()
    _stage(svc, "worlds/W/")

    await sup.start()
    outcome = await svc.apply()
    assert outcome.ok is True

    assert (layout.data_dir / "worlds" / "OtherA" / "keep").read_bytes() == b"OtherA"
    assert (layout.data_dir / "worlds" / "OtherB" / "keep").read_bytes() == b"OtherB"
    assert (layout.data_dir / "server.properties").read_bytes() == props_before
    await sup.stop()


# -- 4.6 the restored-world callback fires with the server's level-name
async def test_restored_world_callback_uses_the_servers_level_name(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    restored: list[str] = []
    svc, layout = _make(sup, on_restored=restored.append)
    _seed_world(layout, "MyWorld", b"orig")
    _stage(svc, "worlds/InternalName/")  # the archive's own level name differs

    await sup.start()
    outcome = await svc.apply()
    assert outcome.ok is True
    assert restored == ["MyWorld"]
    await sup.stop()


# -- 4.7 run state and vendor symlinks restored on every exit path
@pytest.mark.parametrize("failure", [None, "capture", "extract"])
async def test_run_state_and_symlinks_restored_on_every_exit_path(
    make_supervisor, monkeypatch, failure
) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc, layout = _make(sup)
    _seed_world(layout, "Bedrock level", b"orig")
    _stage(svc, "worlds/W/")

    if failure == "capture":
        monkeypatch.setattr(service_mod, "verify_archive", _boom_verify)
    elif failure == "extract":

        def boom(*a, **k):
            raise OSError("simulated mid-extract failure")

        monkeypatch.setattr(service_mod, "_extract_world", boom)

    await sup.start()
    assert sup.state is RunState.RUNNING
    outcome = await svc.apply()

    assert sup.state is RunState.RUNNING
    assert sup.maintenance is None
    if failure is None:
        assert outcome.ok is True
        assert (layout.data_dir / "bedrock_server").is_symlink()
    else:
        assert outcome.ok is False
    await sup.stop()


# -- 4.8 a mid-extract failure names a restorable safety capture ---
async def test_mid_extract_failure_names_the_capture(make_supervisor, monkeypatch) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc, layout = _make(sup)
    _seed_world(layout, "Bedrock level", b"orig")
    _stage(svc, "worlds/W/")

    def boom(*a, **k):
        raise OSError("simulated mid-extract failure")

    monkeypatch.setattr(service_mod, "_extract_world", boom)

    await sup.start()
    outcome = await svc.apply()
    assert outcome.ok is False
    assert outcome.replaced_capture is not None
    assert outcome.replaced_capture in outcome.error
    entry = svc._backup.store.get(outcome.replaced_capture)
    assert entry is not None and entry.restorable is True
    await sup.stop()


# -- 4.9 the busy guard is shared with backup / restore / update ---
async def test_import_and_backup_never_overlap(make_supervisor) -> None:
    sup: Supervisor = make_supervisor(shutdown_timeout=5.0)
    svc, layout = _make(sup)
    _seed_world(layout, "Bedrock level", b"orig")
    _stage(svc, "worlds/W/")

    async with sup.maintenance_scope("backing_up"):
        with pytest.raises(MaintenanceConflictError, match="backing_up"):
            await svc.apply()

    async with sup.maintenance_scope("importing"):
        with pytest.raises(MaintenanceConflictError, match="importing"):
            await svc._backup.capture(reason="manual")


# -- 2.5 the inspection is cached beside the held archive ---------
async def test_second_inspect_does_not_reopen_the_archive(make_supervisor, monkeypatch) -> None:
    sup: Supervisor = make_supervisor()
    svc, _ = _make(sup)
    _stage(svc, "worlds/W/")

    calls = {"n": 0}
    real_open = service_mod.open_archive

    def counting_open(path):
        calls["n"] += 1
        return real_open(path)

    monkeypatch.setattr(service_mod, "open_archive", counting_open)
    first = svc.inspect_held()
    second = svc.inspect_held()
    assert first == second
    assert calls["n"] == 1
