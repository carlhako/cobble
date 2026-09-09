"""Composite ban and unban (tasks 6.1-6.8)."""

from __future__ import annotations

import json

import pytest

from cobble.access.documents import AllowlistFile, PermissionsFile
from cobble.access.enforcement import Enforcement, EnforcementTracker
from cobble.access.service import AccessService, PermissionRefusedError, UnknownPlayerError
from cobble.access.store import open_ban_store
from cobble.supervisor.supervisor import MaintenanceInProgressError
from tests.access.fakes import FakeConsole, FakeSupervisor


class Env:
    def __init__(self, tmp_path, *, running=True, allow_list=False, roster=None):
        self.allow_path = tmp_path / "allowlist.json"
        self.allow_path.write_text("[]")
        self.perm_path = tmp_path / "permissions.json"
        self.perm_path.write_text("[]")
        self.console = FakeConsole(running=running)
        self.sup = FakeSupervisor(running=running)
        self.bans = open_ban_store(tmp_path / "cobble.db")
        self.tracker = EnforcementTracker()
        self._saved_allow_list = allow_list
        self.roster = roster if roster is not None else {"x-target": "Target"}
        self.online = set(self.roster)
        self.saves: list[bool] = []
        self.svc = AccessService(
            self.console,
            self.sup,
            self.tracker,
            saved_allow_list=lambda: self._saved_allow_list,
            ban_store=self.bans,
            is_connected=lambda x: x in self.online,
            permissions_file=PermissionsFile(self.perm_path),
            allowlist_file=AllowlistFile(self.allow_path),
            name_for=self.roster.get,
            roster_names=lambda: dict(self.roster),
            save_allow_list=self._save,
        )

    def _save(self, on: bool) -> None:
        self.saves.append(on)
        self._saved_allow_list = on
        if self.sup.state.name == "RUNNING":
            self.tracker.note(on)

    def allow(self) -> list[dict]:
        return json.loads(self.allow_path.read_text())

    def close(self) -> None:
        self.bans.close()


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path, running=True, allow_list=True)  # enforcement already on by default
    yield e
    e.close()


# -- 6.1 ordered composite; record survives a kick failure -------
async def test_ban_runs_every_step_in_order_for_an_online_player(env) -> None:
    result = await env.svc.ban("x-target", "griefing")
    assert result.steps == (
        "recorded",
        "allowlist_updated",
        "allowlist_reloaded",
        "kick_unconfirmed",  # fake server sends no disconnect
    )
    assert env.bans.is_banned("x-target") is True
    assert "allowlist reload" in env.console.submitted
    assert {e["name"] for e in env.allow()} == set()  # target removed / never present


async def test_the_recorded_ban_survives_a_failure_of_the_kick_step(env, monkeypatch) -> None:
    async def boom(*_a, **_k):
        raise RuntimeError("kick blew up")

    monkeypatch.setattr(env.svc, "kick", boom)
    result = await env.svc.ban("x-target", "griefing")
    assert "recorded" in result.steps
    assert env.bans.is_banned("x-target") is True


# -- 6.2 allowlist entry forms ---------------------------------
async def test_ban_writes_the_stable_identifier_for_a_roster_player(tmp_path) -> None:
    e = Env(tmp_path, running=True, allow_list=True, roster={"x-1": "Renamed Player"})
    e.online = set()  # offline so we skip the kick noise
    try:
        await e.svc.ban("x-1", "reason")
        # target was removed from the allowlist by the ban; add them back via the
        # add path to observe the xuid+name form
        view = await e.svc.allowlist_add("Renamed Player")
        assert view.has_identifier is True
        entry = next(x for x in e.allow() if x["name"] == "Renamed Player")
        assert entry["xuid"] == "x-1"
    finally:
        e.close()


async def test_allowlist_add_for_an_unknown_name_is_name_only(tmp_path) -> None:
    e = Env(tmp_path, running=True, allow_list=True, roster={})
    try:
        view = await e.svc.allowlist_add("Stranger Danger")
        assert view.has_identifier is False
        entry = next(x for x in e.allow() if x["name"] == "Stranger Danger")
        assert "xuid" not in entry
    finally:
        e.close()


# -- 6.3 exclusion preview + confirmation gate ----------------
async def test_ban_while_enforcement_off_reports_who_it_would_exclude(tmp_path) -> None:
    e = Env(
        tmp_path,
        running=True,
        allow_list=False,
        roster={"x-target": "Target", "x-kid": "Kid", "x-mum": "Mum"},
    )
    e.online = {"x-target"}
    try:
        result = await e.svc.ban("x-target", "reason")
        assert result.needs_confirmation is True
        assert set(result.would_exclude) == {"Kid", "Mum"}  # not the target
        assert result.steps == ()
        assert e.bans.is_banned("x-target") is False  # nothing applied
        assert e.allow() == []
        assert e.saves == []
    finally:
        e.close()


# -- 6.4 carry the excluded onto the list --------------------
async def test_confirmed_ban_carries_excluded_players_and_enables_enforcement(tmp_path) -> None:
    e = Env(
        tmp_path,
        running=True,
        allow_list=False,
        roster={"x-target": "Target", "x-kid": "Kid"},
    )
    e.online = set()
    try:
        result = await e.svc.ban("x-target", "reason", confirm=True, permit_excluded=True)
        assert "enforcement_enabled" in result.steps
        assert "excluded_players_permitted" in result.steps
        assert e.saves == [True]
        names = {x["name"] for x in e.allow()}
        assert "Kid" in names
        assert "Target" not in names
    finally:
        e.close()


# -- 6.5 stopped server: durable half only -------------------
async def test_ban_while_stopped_applies_the_durable_half_only(tmp_path) -> None:
    e = Env(tmp_path, running=False, allow_list=True)  # enforcement already saved on
    try:
        result = await e.svc.ban("x-target", "reason")
        assert e.bans.is_banned("x-target") is True
        assert "allowlist_updated" in result.steps
        assert "allowlist_reloaded" not in result.steps
        assert result.kick is None
        assert e.console.submitted == []  # no command issued at all
    finally:
        e.close()


# -- 6.6 unban restores, clears, leaves enforcement alone ----
async def test_unban_restores_the_player_and_clears_the_record(env) -> None:
    env.online = set()
    await env.svc.ban("x-target", "reason")
    env.console.submitted.clear()

    result = await env.svc.unban("x-target")
    assert "allowlist_restored" in result.steps
    assert "ban_cleared" in result.steps
    assert env.bans.is_banned("x-target") is False
    assert any(x["name"] == "Target" for x in env.allow())
    # no enforcement command was issued as a side effect
    assert not any(c in ("allowlist on", "allowlist off") for c in env.console.submitted)


async def test_unban_without_a_record_is_refused(env) -> None:
    with pytest.raises(UnknownPlayerError):
        await env.svc.unban("nobody")


# -- 6.7 the report names the steps carried out -------------
async def test_report_names_the_steps_for_the_online_case(tmp_path) -> None:
    e = Env(tmp_path, running=True, allow_list=True)
    e.online = set()
    try:
        r1 = await e.svc.ban("x-target", "r")
        assert "recorded" in r1.steps and "allowlist_updated" in r1.steps
        assert "allowlist_reloaded" in r1.steps
    finally:
        e.close()


async def test_report_names_the_steps_for_the_stopped_case(tmp_path) -> None:
    e = Env(tmp_path, running=False, allow_list=True)
    try:
        r2 = await e.svc.ban("x-target", "r")
        assert "recorded" in r2.steps
        assert "allowlist_updated" in r2.steps
        assert "allowlist_reloaded" not in r2.steps
    finally:
        e.close()


# -- 6.8 maintenance refuses writes, permits reads ----------
async def test_maintenance_refuses_writes_and_permits_reads(env) -> None:
    env.sup.maintenance = "backup"

    for coro in (
        env.svc.ban("x-target", "r"),
        env.svc.unban("x-target"),
        env.svc.allowlist_add("Someone"),
        env.svc.set_permission("x-target", "operator"),
    ):
        with pytest.raises(MaintenanceInProgressError) as ei:
            await coro
        assert "backup" in str(ei.value)

    # reads still work
    assert env.svc.read_allowlist() == []
    assert env.svc.read_permissions() == []
    assert env.svc.active_bans() == []
    _ = (Enforcement, PermissionRefusedError)
