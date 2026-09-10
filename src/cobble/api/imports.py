"""World-import routes: upload, inspect, discard, apply (section 5, design.md D1).

The upload reads the raw request body stream straight to disk — no multipart
form, so no ``python-multipart`` dependency and one fewer parsing layer on the
path an operator-supplied file travels (design.md D3). Registered under the
single ``/api`` router with the shared ``auth_guard``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, Depends, Request

from cobble.api._shared import auth_guard, conflict
from cobble.supervisor.supervisor import MaintenanceConflictError, SupervisorError
from cobble.worldimport.service import InsufficientSpaceError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


def build_imports_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/import", tags=["import"], dependencies=[Depends(auth_guard)])

    @router.post("/upload", summary="Stream a world archive to the staging slot")
    async def upload(request: Request) -> dict:
        cl = request.headers.get("content-length")
        declared = int(cl) if cl and cl.isdigit() else None
        try:
            return await runtime.imports.receive_upload(request.stream(), declared_size=declared)
        except InsufficientSpaceError as exc:
            raise conflict(exc.code, str(exc)) from exc

    @router.get("", summary="Describe the held archive, or an empty state")
    async def describe() -> dict:
        return {
            **(await runtime.imports.describe_async()),
            "maintenance": runtime.supervisor.maintenance,
        }

    @router.delete("", summary="Discard the held archive")
    async def discard() -> dict:
        runtime.imports.discard()
        return {
            **(await runtime.imports.describe_async()),
            "maintenance": runtime.supervisor.maintenance,
        }

    @router.post("/apply", summary="Apply the held archive over the current world")
    async def apply(confirm_old_version: bool = Body(default=False, embed=True)) -> dict:
        try:
            outcome = await runtime.imports.apply(confirm_old_version=confirm_old_version)
        except (MaintenanceConflictError, SupervisorError) as exc:
            raise conflict(getattr(exc, "code", "conflict"), str(exc)) from exc
        return outcome.to_dict()

    return router
