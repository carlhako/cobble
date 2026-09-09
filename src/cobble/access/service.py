"""The access service: keeps ``allowlist.json``, ``permissions.json``, the
running server, and cobble's ban record consistent with one another
(server-access spec).

It owns:

* **enforcement** — follows the transitions the server prints (via the
  :class:`~cobble.access.enforcement.EnforcementTracker`), asserts the saved
  ``allow-list`` value at every readiness so a divergence self-heals within one
  start (design.md D5), and exposes the hook the configuration service calls to
  push a saved change to the running server;
* **permissions** — reads ``permissions.json`` joined to the roster, and writes a
  level by editing the file, issuing ``permission reload``, and reporting the
  re-read (design.md D1, D7);
* **kick** — the echoed ``kick`` command, resolved by an observed departure whose
  intent is registered beforehand (design.md D6);
* **ban / unban** — the ordered composite of record → allowlist edit → reload →
  ensure enforcement → kick → confirm, and its reverse (design.md D2).

Every file write takes the maintenance interlock (design.md D9); reads do not.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from cobble.access.documents import AllowlistFile, PermissionsDocument, PermissionsFile
from cobble.access.enforcement import Enforcement, EnforcementTracker
from cobble.access.store import BanRecord, BanStore, BanStoreError
from cobble.console.console import Console
from cobble.events.model import Event, EventType
from cobble.logging import get_logger
from cobble.players.kick import KickIntentRegistry
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import (
    MaintenanceInProgressError,
    NotRunningError,
    Supervisor,
)

log = get_logger("access.service")

SavedAllowListFn = Callable[[], bool]
IsConnectedFn = Callable[[str], bool]
NameForFn = Callable[[str], "str | None"]
RosterNamesFn = Callable[[], "dict[str, str]"]  # xuid -> current display name
SaveAllowListFn = Callable[[bool], None]  # persist server.properties allow-list

# BDS prints this (only the first line prefixed) when ``kick`` names a player it
# cannot resolve (design.md Context). Confined to this module.
_NO_TARGET_RE = re.compile(r"No targets matched selector", re.IGNORECASE)

_KICK_TIMEOUT = 5.0


class NotConnectedError(RuntimeError):
    """A moderation action needs the player connected and they are not."""

    code = "player_not_connected"


class PermissionRefusedError(RuntimeError):
    """A permission level the Bedrock server does not define was submitted; the
    file was not touched (task 5.4)."""

    code = "invalid_permission_level"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PermissionView:
    xuid: str
    level: str
    name: str | None  # the roster name for this identifier, or None if unknown

    def to_dict(self) -> dict:
        return {"xuid": self.xuid, "level": self.level, "name": self.name}


@dataclass(frozen=True)
class PermissionResult:
    xuid: str
    level: str  # the level read back from the file after the change
    reloaded: bool  # whether the running server was told to reload

    def to_dict(self) -> dict:
        return {"xuid": self.xuid, "level": self.level, "reloaded": self.reloaded}


class UnknownPlayerError(RuntimeError):
    """A moderation action named an identifier with no recorded sessions."""

    code = "unknown_player"


@dataclass(frozen=True)
class AllowlistEntryView:
    name: str
    xuid: str | None
    has_identifier: bool
    has_played: bool  # whether this player has a recorded session on this server

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "xuid": self.xuid,
            "has_identifier": self.has_identifier,
            "has_played": self.has_played,
        }


@dataclass(frozen=True)
class BanResult:
    xuid: str
    name: str
    # When enabling enforcement would exclude others, the ban is not applied
    # until it is confirmed (design.md Risks; task 6.3).
    needs_confirmation: bool = False
    would_exclude: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    kick: KickResult | None = None
    identifier_written: bool = True  # False when the allowlist entry is name-only

    def to_dict(self) -> dict:
        return {
            "xuid": self.xuid,
            "name": self.name,
            "needs_confirmation": self.needs_confirmation,
            "would_exclude": list(self.would_exclude),
            "steps": list(self.steps),
            "kick": self.kick.to_dict() if self.kick is not None else None,
            "identifier_written": self.identifier_written,
        }


@dataclass(frozen=True)
class UnbanResult:
    xuid: str
    name: str
    steps: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"xuid": self.xuid, "name": self.name, "steps": list(self.steps)}


@dataclass(frozen=True)
class KickResult:
    xuid: str
    command: str
    # exactly one of these is true
    confirmed: bool = False
    unconfirmed: bool = False
    no_target: bool = False

    def to_dict(self) -> dict:
        return {
            "xuid": self.xuid,
            "command": self.command,
            "confirmed": self.confirmed,
            "unconfirmed": self.unconfirmed,
            "no_target": self.no_target,
        }


class AccessService:
    def __init__(
        self,
        console: Console,
        supervisor: Supervisor,
        enforcement: EnforcementTracker,
        *,
        saved_allow_list: SavedAllowListFn,
        ban_store: BanStore | None = None,
        kick_intents: KickIntentRegistry | None = None,
        is_connected: IsConnectedFn | None = None,
        permissions_file: PermissionsFile | None = None,
        allowlist_file: AllowlistFile | None = None,
        name_for: NameForFn | None = None,
        roster_names: RosterNamesFn | None = None,
        save_allow_list: SaveAllowListFn | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], object] | None = None,
    ) -> None:
        self._console = console
        self._sup = supervisor
        self._enforcement = enforcement
        self._saved_allow_list = saved_allow_list
        self._bans = ban_store
        self._kicks = kick_intents if kick_intents is not None else KickIntentRegistry(clock=clock)
        self._is_connected = is_connected or (lambda _x: False)
        self._permissions_file = permissions_file
        self._allowlist_file = allowlist_file
        self._name_for = name_for or (lambda _x: None)
        self._roster_names = roster_names or (lambda: {})
        self._save_allow_list = save_allow_list or (lambda _on: None)
        self._clock = clock
        self._now = now or (lambda: datetime.now(UTC))
        self._last_no_target_at: float = 0.0
        self._tasks: set[asyncio.Task] = set()

        supervisor.subscribe_state(enforcement.on_state_change)

    @property
    def kick_intents(self) -> KickIntentRegistry:
        return self._kicks

    @property
    def enforcement(self) -> EnforcementTracker:
        return self._enforcement

    # -- ban record (safe reads: logged and non-raising — task 3.5) ----
    def is_banned(self, xuid: str) -> bool:
        """Whether ``xuid`` has an active ban, from cobble's own record only
        (design.md D3). A storage failure is logged and reported as not banned so
        the event and status pipelines are unaffected."""
        if self._bans is None:
            return False
        try:
            return self._bans.is_banned(xuid)
        except BanStoreError:
            log.exception("reading ban state for %r failed; reporting not banned", xuid)
            return False

    def ban_record(self, xuid: str) -> BanRecord | None:
        if self._bans is None:
            return None
        try:
            return self._bans.get(xuid)
        except BanStoreError:
            log.exception("reading the ban record for %r failed", xuid)
            return None

    def active_bans(self) -> list[BanRecord]:
        if self._bans is None:
            return []
        try:
            return self._bans.active_bans()
        except BanStoreError:
            log.exception("reading active bans failed; reporting none")
            return []

    def banned_count(self) -> int:
        if self._bans is None:
            return 0
        try:
            return self._bans.count_active()
        except BanStoreError:
            log.exception("counting active bans failed; reporting zero")
            return 0

    # -- bus callback ------------------------------------------------
    def on_event(self, event: Event) -> None:
        """Fast, non-raising. Feeds enforcement transitions to the tracker,
        watches for the ``No targets matched selector`` line a failed kick
        prints, and asserts the saved enforcement value at readiness."""
        self._enforcement.on_event(event)
        if event.type is EventType.RAW_OUTPUT and _NO_TARGET_RE.search(event.raw):
            self._last_no_target_at = self._clock()
        if event.type is EventType.SERVER_READY:
            self._spawn(self._on_ready(), "cobble-access-ready")

    def _spawn(self, coro, name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- readiness assertion (task 2.4) ---------------------------
    async def _on_ready(self) -> None:
        try:
            if self._sup.state is not RunState.RUNNING:
                waiter = getattr(self._sup, "wait_for_state", None)
                if waiter is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(waiter(RunState.RUNNING), timeout=30)
            await self.assert_saved_enforcement()
        except Exception:
            log.exception("asserting saved allowlist enforcement at readiness failed")

    async def assert_saved_enforcement(self) -> None:
        """Instruct the running server to match the saved ``allow-list`` value.
        A no-op if the server is not running."""
        want_on = self._saved_allow_list()
        await self._send_enforcement(want_on)

    async def set_enforcement(self, on: bool) -> None:
        """Turn allowlist enforcement on or off on the running server (used by the
        access router). Raises :class:`NotRunningError` if the server is stopped."""
        if self._sup.state is not RunState.RUNNING:
            raise NotRunningError("the server is not running")
        await self._send_enforcement(on)

    async def _send_enforcement(self, on: bool) -> None:
        if self._sup.state is not RunState.RUNNING:
            log.info(
                "server not running; deferring allowlist %s to the next start",
                "on" if on else "off",
            )
            return
        command = "allowlist on" if on else "allowlist off"
        try:
            # Echoed to the console: a change to who may join is worth seeing
            # (the same rationale as kick — design.md D6).
            await self._console.submit_command(command)
        except NotRunningError:
            log.info("server went away before %r could be issued", command)
            return
        # Record the transition immediately so the reported state is correct
        # without waiting for the announcement to round-trip through the parser;
        # the observed line will confirm it.
        self._enforcement.note(on)

    # -- maintenance interlock (design.md D9; task 6.8) -------
    def _check_maintenance(self, operation: str) -> None:
        if self._sup.maintenance is not None:
            raise MaintenanceInProgressError(
                f"a {self._sup.maintenance} operation is in progress; cannot {operation} right now"
            )

    # -- permissions (design.md D1, D7; tasks 5.1-5.5) --------
    def read_permissions(self) -> list[PermissionView]:
        """Every permission record, each joined to the name cobble's roster holds
        for that identifier. A record whose identifier is absent from the roster
        is still reported, with no name (task 5.1)."""
        if self._permissions_file is None:
            return []
        doc = self._permissions_file.read()
        return [
            PermissionView(xuid=e.xuid, level=e.level, name=self._name_for(e.xuid))
            for e in doc.entries
        ]

    def permission_level(self, xuid: str) -> str:
        """The level held by ``xuid`` per the file — ``"member"`` when the file
        has no row for them (BDS's implicit default)."""
        if self._permissions_file is None:
            return "member"
        entry = self._permissions_file.read().find(xuid)
        return entry.level if entry is not None else "member"

    async def set_permission(self, xuid: str, level: str) -> PermissionResult:
        """Write ``xuid``'s permission level, issue ``permission reload`` if the
        server is running, then report the level read back from the file — never
        from any acknowledgement, which BDS does not send (design.md D7).

        Raises :class:`PermissionRefusedError` (nothing written) for a level BDS
        does not define, and :class:`MaintenanceInProgressError` during
        maintenance."""
        self._check_maintenance("change permissions")
        level = level.strip().lower()
        if level not in PermissionsDocument.VALID_LEVELS:
            allowed = ", ".join(PermissionsDocument.VALID_LEVELS)
            raise PermissionRefusedError(
                f"{level!r} is not a permission level the server defines; use one of: {allowed}"
            )
        if self._permissions_file is None:
            raise PermissionRefusedError("permissions.json is not available")

        self._permissions_file.mutate(lambda d: d.set_level(xuid, level))

        reloaded = False
        if self._sup.state is RunState.RUNNING:
            with contextlib.suppress(NotRunningError):
                await self._console.submit_command("permission reload")
                reloaded = True

        # The re-read is authoritative; a silent write is confirmed this way
        # (design.md D7; tasks 5.2, 5.3).
        return PermissionResult(xuid=xuid, level=self.permission_level(xuid), reloaded=reloaded)

    # -- allowlist reads/writes (server-access spec; tasks 6.2, 7.x) --
    def read_allowlist(self) -> list[AllowlistEntryView]:
        if self._allowlist_file is None:
            return []
        doc = self._allowlist_file.read()
        roster = self._roster_names()
        roster_lc = {n.casefold() for n in roster.values()}
        out: list[AllowlistEntryView] = []
        for e in doc.entries:
            played = (e.xuid in roster) or (e.name.casefold() in roster_lc)
            out.append(
                AllowlistEntryView(
                    name=e.name,
                    xuid=e.xuid,
                    has_identifier=e.has_identifier,
                    has_played=played,
                )
            )
        return out

    def allowlist_readable(self) -> bool:
        return self._allowlist_file is None or self._allowlist_file.read().readable

    def _xuid_for_name(self, name: str) -> str | None:
        low = name.casefold()
        for xuid, disp in self._roster_names().items():
            if disp.casefold() == low:
                return xuid
        return None

    async def _reload_allowlist(self) -> bool:
        if self._sup.state is not RunState.RUNNING:
            return False
        with contextlib.suppress(NotRunningError):
            await self._console.submit_command("allowlist reload")
            return True
        return False

    async def allowlist_add(self, name: str) -> AllowlistEntryView:
        """Add ``name`` to the allowlist. A player cobble holds a stable
        identifier for gets an entry carrying both that identifier and the name
        (rename-proof — design.md D4); a name cobble has no identifier for is
        stored name-only and reported as such (task 6.2)."""
        self._check_maintenance("change the allowlist")
        if self._allowlist_file is None:
            raise UnknownPlayerError("allowlist.json is not available")
        xuid = self._xuid_for_name(name)
        self._allowlist_file.mutate(lambda d: d.upsert(name, xuid=xuid))
        await self._reload_allowlist()
        return AllowlistEntryView(
            name=name,
            xuid=xuid,
            has_identifier=xuid is not None,
            has_played=xuid is not None,
        )

    async def allowlist_remove(self, *, xuid: str | None = None, name: str | None = None) -> bool:
        self._check_maintenance("change the allowlist")
        if self._allowlist_file is None:
            raise UnknownPlayerError("allowlist.json is not available")
        removed_holder: list[bool] = [False]

        def _mut(d):
            removed_holder[0] = d.remove(xuid=xuid, name=name)

        self._allowlist_file.mutate(_mut)
        if removed_holder[0]:
            await self._reload_allowlist()
        return removed_holder[0]

    # -- enforcement helpers (design.md D2, D5) ---------------
    def _enforcement_currently_on(self) -> bool:
        if self._sup.state is RunState.RUNNING and self._enforcement.observed:
            return self._enforcement.state is Enforcement.ON
        return self._saved_allow_list()

    def would_exclude(self, *, ignore_xuid: str | None = None) -> list[str]:
        """The players in cobble's roster who are not on the allowlist — i.e. who
        turning enforcement on would lock out (design.md Risks; task 6.3)."""
        if self._allowlist_file is None:
            return []
        doc = self._allowlist_file.read()
        allowed_xuids = {e.xuid for e in doc.entries if e.xuid}
        allowed_names = {e.name.casefold() for e in doc.entries}
        excluded: list[str] = []
        for xuid, name in sorted(self._roster_names().items(), key=lambda kv: kv[1].casefold()):
            if xuid == ignore_xuid:
                continue
            if xuid in allowed_xuids or name.casefold() in allowed_names:
                continue
            excluded.append(name)
        return excluded

    # -- composite ban / unban (design.md D2; tasks 6.1-6.7) --
    async def ban(
        self,
        xuid: str,
        reason: str = "",
        *,
        confirm: bool = False,
        permit_excluded: bool = False,
    ) -> BanResult:
        """Ban a player: the ordered composite of recording the ban, removing
        them from the allowlist, reloading it, ensuring enforcement is on,
        kicking them, and confirming (design.md D2).

        When enforcement is off, enabling it is a server-wide change: the players
        it would exclude are returned and nothing is applied until ``confirm`` is
        set (task 6.3). ``permit_excluded`` carries those players onto the
        allowlist as part of the same confirmed action (task 6.4).
        """
        self._check_maintenance("ban a player")
        name = self._roster_names().get(xuid)
        if name is None:
            raise UnknownPlayerError(f"no player {xuid!r} on record")

        already_on = self._enforcement_currently_on()
        if not already_on and not confirm:
            return BanResult(
                xuid=xuid,
                name=name,
                needs_confirmation=True,
                would_exclude=tuple(self.would_exclude(ignore_xuid=xuid)),
            )

        running = self._sup.state is RunState.RUNNING
        steps: list[str] = []

        # 1. record first, so the ban survives a later step failing (task 6.1)
        identifier_written = True
        if self._bans is not None:
            with contextlib.suppress(BanStoreError):
                self._bans.record_ban(xuid, name, reason, self._now())
                steps.append("recorded")

        # 2. allowlist: remove the target; optionally carry the excluded on
        carry = self.would_exclude(ignore_xuid=xuid) if (permit_excluded and not already_on) else []

        def _mut(d):
            d.remove(xuid=xuid, name=name)
            for other_name in carry:
                d.upsert(other_name, xuid=self._xuid_for_name(other_name))

        if self._allowlist_file is not None:
            self._allowlist_file.mutate(_mut)
            steps.append("allowlist_updated")
        if carry:
            steps.append("excluded_players_permitted")

        # 3. reload so a running server picks the change up
        if running and await self._reload_allowlist():
            steps.append("allowlist_reloaded")

        # 4. ensure enforcement is on (persist + apply — design.md D5)
        if not already_on:
            with contextlib.suppress(Exception):
                self._save_allow_list(True)
            steps.append("enforcement_enabled")

        # 5. kick (only meaningful while running and the player is connected)
        kick_result: KickResult | None = None
        if running and self._is_connected(xuid):
            try:
                kick_result = await self.kick(xuid, name, reason)
                steps.append("kicked" if kick_result.confirmed else "kick_unconfirmed")
            except (NotConnectedError, NotRunningError):
                pass
            except Exception:
                log.exception("ban: the kick step failed; the ban record stands")

        return BanResult(
            xuid=xuid,
            name=name,
            steps=tuple(steps),
            kick=kick_result,
            would_exclude=tuple(carry),
            identifier_written=identifier_written,
        )

    async def unban(self, xuid: str) -> UnbanResult:
        """Lift a recorded ban: restore the player to the allowlist by the name
        recorded at ban time and clear the record. Enforcement is left exactly as
        it stands — a ban that enabled it does not disable it on unban
        (design.md D5; task 6.6)."""
        self._check_maintenance("unban a player")
        rec = self._bans.get(xuid) if self._bans is not None else None
        if rec is None:
            raise UnknownPlayerError(f"no ban on record for {xuid!r}")

        name = rec.name
        steps: list[str] = []
        if self._allowlist_file is not None:
            roster_has = xuid in self._roster_names()
            self._allowlist_file.mutate(lambda d: d.upsert(name, xuid=xuid if roster_has else None))
            steps.append("allowlist_restored")
        if self._bans is not None:
            with contextlib.suppress(BanStoreError):
                self._bans.lift_ban(xuid, self._now())
                steps.append("ban_cleared")
        if self._sup.state is RunState.RUNNING and await self._reload_allowlist():
            steps.append("allowlist_reloaded")
        # deliberately no enforcement command (task 6.6)
        return UnbanResult(xuid=xuid, name=name, steps=tuple(steps))

    # -- kick (design.md D6; tasks 4.1-4.6) -------------------
    async def kick(
        self,
        xuid: str,
        name: str,
        reason: str = "",
        *,
        wait_timeout: float = _KICK_TIMEOUT,
    ) -> KickResult:
        """Disconnect a connected player. Sends ``kick <name> [reason]`` through
        the echoed console path and resolves on an observed departure for
        ``xuid`` within ``timeout``.

        Refused — with nothing sent — when the server is not running
        (:class:`NotRunningError`) or the player is not connected
        (:class:`NotConnectedError`). A kick that produces no departure in time is
        reported ``unconfirmed`` (or ``no_target`` if the server said it could
        not find the player), never as a plain success or a failure.
        """
        if self._sup.state is not RunState.RUNNING:
            raise NotRunningError("the server is not running")
        if not self._is_connected(xuid):
            raise NotConnectedError(f"{name or xuid} is not connected")

        command = f"kick {name}" + (f" {reason}" if reason else "")
        # Register the intent BEFORE the command is sent: the disconnect line is
        # identical to a voluntary leave and arrives ~5ms after the ack, so there
        # is no window to decide afterwards (design.md D6).
        intent = self._kicks.register(xuid, reason, ttl=wait_timeout)
        sent_at = self._clock()
        try:
            await self._console.submit_command(command)  # echoed to console clients
        except NotRunningError:
            self._kicks.discard(xuid)
            raise

        try:
            await asyncio.wait_for(intent.satisfied.wait(), wait_timeout)
            return KickResult(xuid=xuid, command=command, confirmed=True)
        except TimeoutError:
            self._kicks.discard(xuid)
            if self._last_no_target_at >= sent_at:
                return KickResult(xuid=xuid, command=command, no_target=True)
            return KickResult(xuid=xuid, command=command, unconfirmed=True)

    # -- lifecycle ----------------------------------------------
    def apply_enforcement(self, on: bool) -> None:
        """Sync fire-and-forget wrapper for the configuration service: schedule
        the enforcement instruction on the running loop (task 2.5)."""
        try:
            self._spawn(self._send_enforcement(on), "cobble-access-apply-enforcement")
        except RuntimeError:
            log.warning("no running loop; allowlist enforcement not applied to the server")

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
