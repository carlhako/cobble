"""Reading and writing operator permissions (tasks 5.1-5.5)."""

from __future__ import annotations

import json

import pytest

from cobble.access.documents import PermissionsFile
from cobble.access.enforcement import EnforcementTracker
from cobble.access.service import AccessService, PermissionRefusedError
from tests.access.fakes import FakeConsole, FakeSupervisor

ROSTER = {"x-alex": "Alex", "x-sam": "Sam"}


def _service(tmp_path, *, running=True):
    path = tmp_path / "permissions.json"
    path.write_text(
        json.dumps(
            [
                {"xuid": "x-alex", "permission": "operator"},
                {"xuid": "x-stranger", "permission": "operator"},
            ]
        )
    )
    console = FakeConsole(running=running)
    sup = FakeSupervisor(running=running)
    svc = AccessService(
        console,
        sup,
        EnforcementTracker(),
        saved_allow_list=lambda: False,
        permissions_file=PermissionsFile(path),
        name_for=ROSTER.get,
    )
    return svc, console, sup, path


# -- 5.1 read joins identifiers to roster names -------------------
def test_read_reports_every_record_with_its_name_where_known(tmp_path) -> None:
    svc, *_ = _service(tmp_path)
    by = {v.xuid: v for v in svc.read_permissions()}
    assert by["x-alex"].name == "Alex"
    assert by["x-alex"].level == "operator"
    # an identifier absent from the roster is still reported, with no name
    assert by["x-stranger"].name is None
    assert by["x-stranger"].level == "operator"


# -- 5.2 / 5.3 write, reload, and report from the re-read --------
async def test_write_reports_the_level_read_back_from_the_file(tmp_path) -> None:
    svc, console, _sup, path = _service(tmp_path)
    result = await svc.set_permission("x-sam", "operator")
    assert result.level == "operator"
    assert result.reloaded is True
    assert "permission reload" in console.submitted
    on_disk = {e["xuid"]: e["permission"] for e in json.loads(path.read_text())}
    assert on_disk["x-sam"] == "operator"


async def test_a_silent_write_is_still_reported_correctly(tmp_path) -> None:
    # FakeConsole emits nothing at all for the change; the outcome comes purely
    # from re-reading the file (design.md D7).
    svc, _console, _sup, _path = _service(tmp_path)
    result = await svc.set_permission("x-alex", "visitor")
    assert result.level == "visitor"


async def test_setting_member_removes_the_row_and_reads_back_as_member(tmp_path) -> None:
    svc, _console, _sup, path = _service(tmp_path)
    result = await svc.set_permission("x-alex", "member")
    assert result.level == "member"
    xuids = {e["xuid"] for e in json.loads(path.read_text())}
    assert "x-alex" not in xuids


# -- 5.4 refuse an undefined level, nothing written --------------
async def test_an_undefined_level_is_refused_with_a_reason(tmp_path) -> None:
    svc, console, _sup, path = _service(tmp_path)
    before = path.read_text()
    with pytest.raises(PermissionRefusedError) as ei:
        await svc.set_permission("x-alex", "superadmin")
    assert "superadmin" in str(ei.value)
    assert path.read_text() == before  # file untouched
    assert console.submitted == []


# -- 5.5 offline player in the roster --------------------------
async def test_offline_player_write_and_reload_still_happen(tmp_path) -> None:
    # server running, player not connected — the file write + reload path is the
    # same; the console command can op someone BDS could not resolve by name.
    svc, console, _sup, path = _service(tmp_path)
    result = await svc.set_permission("x-sam", "operator")  # x-sam is offline
    assert result.reloaded is True
    assert "permission reload" in console.submitted
    on_disk = {e["xuid"]: e["permission"] for e in json.loads(path.read_text())}
    assert on_disk["x-sam"] == "operator"


async def test_write_while_stopped_persists_without_a_reload(tmp_path) -> None:
    svc, console, _sup, path = _service(tmp_path, running=False)
    result = await svc.set_permission("x-sam", "operator")
    assert result.reloaded is False
    assert console.submitted == []
    on_disk = {e["xuid"]: e["permission"] for e in json.loads(path.read_text())}
    assert on_disk["x-sam"] == "operator"
