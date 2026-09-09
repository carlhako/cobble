"""Runtime wiring: the single object that owns cobble's long-lived components
and registers the HTTP interface onto the app.

Wiring (design.md):

    supervisor stdout ──> parse_line ──> EventBus ──┬─> StatusTracker.on_event
                                                    └─> (SSE event consumers, later)
    ConsoleBuffer (owned by supervisor) ──listener──> Console fan-out ──> SSE clients
    StatusTracker ──> status SSE clients

First-run bootstrap (acquiring a Bedrock installation when none exists) runs in
the background so a slow ~100 MB download never blocks the web interface from
loading. Its progress is surfaced in status; a failed bootstrap can be retried
through the interface without restarting cobble.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from fastapi import FastAPI

from cobble.access.documents import AllowlistFile, PermissionsFile
from cobble.access.enforcement import EnforcementTracker
from cobble.access.service import AccessService
from cobble.access.store import BanStoreError
from cobble.access.store import open_ban_store as _open_ban_store
from cobble.acquisition.bootstrap import bootstrap_if_needed
from cobble.acquisition.layout import Layout
from cobble.acquisition.migration import LayoutMigration, MigrationError
from cobble.acquisition.preflight import run_preflight
from cobble.acquisition.version_source import try_resolve_current_version
from cobble.backup.service import BackupService
from cobble.config.service import ConfigService
from cobble.console.console import Console
from cobble.events.bus import EventBus
from cobble.events.parser import parse_line
from cobble.gamerules.manager import GameruleManager
from cobble.gamerules.service import GameruleService
from cobble.gamerules.storage import GameruleStorageError
from cobble.gamerules.storage import open_store as open_gamerule_store
from cobble.logging import get_logger
from cobble.players.service import PlayerHistoryService
from cobble.players.storage import PlayerHistoryError, PlayerStore, open_store
from cobble.schedule import Scheduler
from cobble.settings import Settings
from cobble.status.tracker import StatusTracker
from cobble.supervisor.supervisor import Supervisor
from cobble.update.service import UpdateService

log = get_logger("runtime")


@dataclass
class BootstrapStatus:
    # skipped | not_needed | running | done | failed
    state: str = "skipped"
    detail: str = ""


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.layout = Layout.from_settings(settings)
        self.bus = EventBus()
        self.supervisor = Supervisor(
            settings,
            self.layout,
            line_sink=lambda line: self.bus.publish(parse_line(line)),
        )
        self.bootstrap = BootstrapStatus()
        self.backup = BackupService(settings, self.layout, self.supervisor)
        self.update = UpdateService(settings, self.layout, self.supervisor, self.backup)
        self.scheduler = Scheduler(settings, self.backup, self.update)
        self.migration = LayoutMigration(settings, self.layout, self.supervisor, self.backup)
        self.console = Console(self.supervisor)
        # Live allowlist-enforcement state, learned by observing the server's
        # announcements (M6, design.md D5).
        self.enforcement = EnforcementTracker()
        # A successful configuration save pushes the new pending state to clients
        # (server-status spec, task 5.2); start/restart pushes happen via the
        # tracker's run-state subscription.
        self.config = ConfigService(
            settings,
            self.layout,
            self.supervisor,
            on_change=lambda: self.status.notify(),
            enforcement=self.enforcement,
            apply_enforcement=lambda on: self.access.apply_enforcement(on),
        )

        # Gamerule editing (M5). Shares ``cobble.db`` with player history; a
        # database that cannot be opened disables gamerule editing for the run
        # (the API returns 503) and the server still starts.
        self.gamerule_store = None
        self.gamerules: GameruleManager | None = None
        try:
            self.gamerule_store = open_gamerule_store(settings.player_db_file)
        except GameruleStorageError:
            log.exception("gamerule storage unavailable; gamerule editing disabled this run")
        if self.gamerule_store is not None:
            self.gamerules = GameruleManager(
                GameruleService(self.console),
                self.gamerule_store,
                self.supervisor,
                world_name=lambda: self.config.worlds().current,
                on_report=lambda: self.status.notify(),
            )
            self.bus.subscribe(self.gamerules.on_event)
            # A completed restore names the world so the next readiness repairs
            # its gamerules rather than adopting the reverted set (design.md D6).
            self.backup.set_on_restored(self.gamerules.mark_restored)

        # Durable player history (M4). A database that cannot be opened is
        # surfaced and the server still starts (server-players spec); the roster
        # simply records nothing this run.
        self.players: PlayerStore | None = None
        self.player_history: PlayerHistoryService | None = None
        try:
            self.players = open_store(settings.player_db_file)
        except PlayerHistoryError:
            log.exception("player history unavailable; the roster will not record this run")
        if self.players is not None:
            self.player_history = PlayerHistoryService(
                self.players,
                self.supervisor,
                self.bus,
                checkpoint_seconds=settings.player_history_checkpoint_seconds,
            )

        # Access control (M6): the allowlist, permissions, enforcement state, and
        # the ban record. A ban store that cannot be opened disables the durable
        # ban record for the run; the rest of access still works.
        self.ban_store = None
        try:
            self.ban_store = _open_ban_store(settings.player_db_file)
        except BanStoreError:
            log.exception("ban record unavailable; bans will not be recorded this run")
        self.access = AccessService(
            self.console,
            self.supervisor,
            self.enforcement,
            saved_allow_list=self.config.saved_allow_list,
            ban_store=self.ban_store,
            kick_intents=(
                self.player_history.kick_intents if self.player_history is not None else None
            ),
            is_connected=self._player_online,
            permissions_file=PermissionsFile(self.layout.data_dir / "permissions.json"),
            allowlist_file=AllowlistFile(self.layout.data_dir / "allowlist.json"),
            name_for=lambda xuid: self._roster_names().get(xuid),
            roster_names=self._roster_names,
            save_allow_list=lambda on: self.config.write({"allow-list": "true" if on else "false"}),
        )
        self.bus.subscribe(self.access.on_event)

        self.status = StatusTracker(
            self.supervisor,
            bootstrap=self.bootstrap,
            update=self.update,
            backup=self.backup,
            scheduler=self.scheduler,
            config=self.config,
            gamerules=self.gamerules,
            access=self.access,
        )
        self.bus.subscribe(self.status.on_event)

        self._app: FastAPI | None = None
        self._bootstrap_task: asyncio.Task[None] | None = None

    # -- access-service collaborators -------------------------------
    def _roster_names(self) -> dict[str, str]:
        """xuid -> current display name for every player with a recorded session
        (the identity join the access service needs — design.md Context)."""
        if self.players is None:
            return {}
        from datetime import UTC, datetime

        try:
            return {e.xuid: e.gamertag for e in self.players.roster(now=datetime.now(UTC))}
        except Exception:
            log.exception("building the roster name map failed; treating it as empty")
            return {}

    def _player_online(self, xuid: str) -> bool:
        if self.players is None:
            return False
        try:
            return self.players.has_open_session(xuid)
        except Exception:
            log.exception("checking whether %r is online failed", xuid)
            return False

    def attach(self, app: FastAPI) -> None:
        self._app = app
        from cobble.api import build_api_router

        app.include_router(build_api_router(self))

    async def startup(self) -> None:
        log.info("cobble runtime starting")
        pre = run_preflight()
        if not pre.ok:
            log.error("platform preflight failed: %s", "; ".join(pre.failures))

        if self.player_history is not None:
            # Close sessions a previous run left open before the recorder can
            # write any new event (server-players spec; tasks 4.2/4.3).
            self.player_history.reconcile()
            await self.player_history.start()

        # Bootstrap + restore run in the background: the app is servable at once.
        self._bootstrap_task = asyncio.create_task(
            self._bootstrap_then_restore(), name="cobble-bootstrap"
        )

    async def _bootstrap_then_restore(self) -> None:
        if self.settings.bootstrap_on_start:
            await self.run_bootstrap()
        else:
            self.bootstrap.state = "skipped"
            self.bootstrap.detail = "bootstrap_on_start is disabled"
            log.info("bootstrap_on_start is disabled; skipping first-run acquisition")
        await self._migrate_layout()
        try:
            await self.supervisor.restore()
        except Exception:
            log.exception("restore failed")
        try:
            await self.scheduler.start()
        except Exception:
            log.exception("scheduler failed to start")

    async def _migrate_layout(self) -> None:
        """Relocate a pre-separation (M1) installation before any server start
        (task 4.5). A fresh or already-separated install is a no-op."""
        try:
            if not self.migration.needs_migration():
                return
            outcome = await self.migration.run()
            if outcome.migrated:
                log.info("layout migration: %s", outcome.reason)
            else:
                log.warning("layout migration not completed: %s", outcome.reason)
        except MigrationError:
            log.exception("layout migration could not run")
        except Exception:
            log.exception("layout migration failed unexpectedly")

    async def run_bootstrap(self) -> BootstrapStatus:
        """Acquire and activate a Bedrock installation if none is present.
        Safe to call again after a failure. Never raises."""
        if self.layout.has_installation():
            self.bootstrap.state = "done"
            self.bootstrap.detail = f"installed {self.layout.installed_version()}"
            return self.bootstrap

        self.bootstrap.state = "running"
        self.bootstrap.detail = "resolving the current Bedrock server version"
        self.status.notify()
        log.info("first-run bootstrap: %s", self.bootstrap.detail)
        try:
            resolved = await asyncio.to_thread(try_resolve_current_version, self.settings)
            if resolved is not None:
                self.bootstrap.detail = (
                    f"downloading {resolved.version} from {resolved.download_url}"
                )
                self.status.notify()
                log.info("first-run bootstrap: %s", self.bootstrap.detail)
            outcome = await asyncio.to_thread(bootstrap_if_needed, self.settings, self.layout)
            self.bootstrap.state = "done"
            self.bootstrap.detail = outcome.message
            log.info("bootstrap: %s", outcome.message)
        except Exception as exc:  # version resolution, download, extraction
            self.bootstrap.state = "failed"
            self.bootstrap.detail = str(exc)
            log.exception(
                "first-run bootstrap failed; the server can be started once "
                "an installation is present"
            )
        self.status.notify()
        return self.bootstrap

    async def shutdown(self) -> None:
        log.info("cobble runtime stopping")
        if self._bootstrap_task is not None:
            self._bootstrap_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._bootstrap_task
        await self.scheduler.stop()
        await self.supervisor.aclose()
        await self.access.aclose()
        if self.ban_store is not None:
            self.ban_store.close()
        if self.gamerules is not None:
            await self.gamerules.aclose()
        if self.player_history is not None:
            # After aclose(): the supervisor's clean stop has already fired the
            # pre-stop hook that closes any still-open session.
            await self.player_history.aclose()
