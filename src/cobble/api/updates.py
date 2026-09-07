"""Update routes: check, apply, clear the failed-version record, and failed-update
diagnostics (section 8, tasks 8.1, 8.4).

Registered under the single ``/api`` router with the shared ``auth_guard``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, Depends

from cobble.api._shared import auth_guard, conflict
from cobble.supervisor.supervisor import MaintenanceConflictError, SupervisorError
from cobble.update.service import UpdateConflictError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


def build_updates_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/updates", tags=["updates"], dependencies=[Depends(auth_guard)])

    @router.post("/check", summary="Check the vendor for a newer Bedrock version")
    async def check() -> dict:
        return (await runtime.update.check()).to_dict()

    @router.post("/apply", summary="Check and apply an available update now")
    async def apply() -> dict:
        try:
            result = await runtime.update.apply(reason="manual")
        except UpdateConflictError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except (MaintenanceConflictError, SupervisorError) as exc:
            raise conflict(getattr(exc, "code", "conflict"), str(exc)) from exc
        return result.to_dict()

    @router.post("/clear-failed", summary="Clear the record of a version that failed an update")
    async def clear_failed(version: str | None = Body(default=None, embed=True)) -> dict:
        cleared = runtime.update.clear_failed(version)
        return {"cleared": cleared}

    @router.get("/diagnostics", summary="Diagnostics from the most recent failed update")
    async def diagnostics() -> dict:
        return {"diagnostics": runtime.update.diagnostics()}

    return router
