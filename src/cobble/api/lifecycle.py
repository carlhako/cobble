"""Lifecycle routes: start, stop, restart (server-lifecycle, web-ui-shell).

All three are state-changing and sit under one router that depends on
``auth_guard``. An invalid transition returns 409 with a distinguishable
``error`` code so the interface can report the specific reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from cobble.api._shared import auth_guard, http_error_from_supervisor
from cobble.supervisor.supervisor import SupervisorError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


def build_lifecycle_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(
        prefix="/server",
        tags=["lifecycle"],
        dependencies=[Depends(auth_guard)],
    )

    def _status() -> dict:
        return runtime.status.snapshot().to_dict()

    @router.post("/start", summary="Start the Bedrock server")
    async def start() -> dict:
        try:
            await runtime.supervisor.start()
        except SupervisorError as exc:
            raise http_error_from_supervisor(exc) from exc
        return _status()

    @router.post("/stop", summary="Stop the Bedrock server cleanly")
    async def stop() -> dict:
        try:
            await runtime.supervisor.stop()
        except SupervisorError as exc:
            raise http_error_from_supervisor(exc) from exc
        return _status()

    @router.post("/restart", summary="Restart the Bedrock server")
    async def restart() -> dict:
        try:
            await runtime.supervisor.restart()
        except SupervisorError as exc:
            raise http_error_from_supervisor(exc) from exc
        return _status()

    return router
