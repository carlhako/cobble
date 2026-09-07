"""Runtime wiring: the single object that owns cobble's long-lived components
and registers the HTTP interface onto the app.

Wiring (design.md):

    supervisor stdout ──> parse_line ──> EventBus ──┬─> StatusTracker.on_event
                                                    └─> (SSE event consumers, later)
    ConsoleBuffer (owned by supervisor) ──listener──> Console fan-out ──> SSE clients
    StatusTracker ──> status SSE clients

On startup the runtime bootstraps a Bedrock installation if none exists (a
failure here is logged and surfaced, never fatal) and restores the server if it
was running when cobble last stopped. On shutdown it stops the child cleanly.
"""

from __future__ import annotations

from fastapi import FastAPI

from cobble.acquisition.bootstrap import bootstrap_if_needed
from cobble.acquisition.layout import Layout
from cobble.acquisition.preflight import run_preflight
from cobble.acquisition.version_source import VersionResolutionError
from cobble.console.console import Console
from cobble.events.bus import EventBus
from cobble.events.parser import parse_line
from cobble.logging import get_logger
from cobble.settings import Settings
from cobble.status.tracker import StatusTracker
from cobble.supervisor.supervisor import Supervisor

log = get_logger("runtime")


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
        self.console = Console(self.supervisor)
        self.status = StatusTracker(self.supervisor)
        self.bus.subscribe(self.status.on_event)
        self._app: FastAPI | None = None

    def attach(self, app: FastAPI) -> None:
        self._app = app
        from cobble.api import build_api_router

        app.include_router(build_api_router(self))

    async def startup(self) -> None:
        log.info("cobble runtime starting")
        pre = run_preflight()
        if not pre.ok:
            log.error("platform preflight failed: %s", "; ".join(pre.failures))

        if not self.settings.bootstrap_on_start:
            log.info("bootstrap_on_start is disabled; skipping first-run acquisition")
        try:
            if self.settings.bootstrap_on_start:
                outcome = bootstrap_if_needed(self.settings, self.layout)
                log.info("bootstrap: %s", outcome.message)
        except VersionResolutionError as exc:
            # A version-check failure is a surfaced non-event: it must never block
            # startup or stop a running server (design.md — Risks).
            log.warning("first-run bootstrap could not resolve a version: %s", exc)
        except Exception:
            log.exception("first-run bootstrap failed; continuing without an installation")

        await self.supervisor.restore()

    async def shutdown(self) -> None:
        log.info("cobble runtime stopping")
        await self.supervisor.aclose()
