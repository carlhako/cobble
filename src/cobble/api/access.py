"""Access-control routes (server-access spec, section 7).

* ``GET  /api/access``               — the allowlist, permissions, enforcement
                                        state, and active ban records (read-only,
                                        unauthenticated like ``/api/status``)
* ``POST /api/access/allowlist``      — add a player to the allowlist
* ``DELETE /api/access/allowlist``    — remove a player from the allowlist
* ``POST /api/access/permissions``    — set a player's permission level
* ``POST /api/access/enforcement``    — turn allowlist enforcement on or off

Every state-changing route depends on ``auth_guard`` exactly like the other
state-changing routers (design.md D8; task 7.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cobble.access.documents import UnreadableDocumentError
from cobble.access.service import PermissionRefusedError, UnknownPlayerError
from cobble.api._shared import auth_guard, conflict
from cobble.supervisor.supervisor import MaintenanceInProgressError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


class AllowlistAdd(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class PermissionSet(BaseModel):
    xuid: str = Field(min_length=1, max_length=64)
    level: str = Field(min_length=1, max_length=32)


class EnforcementSet(BaseModel):
    enabled: bool


def build_access_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/access", tags=["access"])

    def _svc():
        return runtime.access

    @router.get("", summary="The allowlist, permissions, enforcement state, and bans")
    async def read() -> dict:
        svc = _svc()
        try:
            entries = [e.to_dict() for e in svc.read_allowlist()]
            readable = svc.allowlist_readable()
        except UnreadableDocumentError:
            entries, readable = [], False
        return {
            "allowlist": {"readable": readable, "entries": entries},
            "permissions": [p.to_dict() for p in svc.read_permissions()],
            "enforcement": runtime.config.enforcement_view().to_dict(),
            "bans": [b.to_dict() for b in svc.active_bans()],
        }

    @router.post(
        "/allowlist",
        summary="Add a player to the allowlist",
        dependencies=[Depends(auth_guard)],
    )
    async def allowlist_add(body: AllowlistAdd) -> dict:
        try:
            view = await _svc().allowlist_add(body.name)
        except MaintenanceInProgressError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except UnknownPlayerError as exc:
            raise HTTPException(
                status_code=503, detail={"error": exc.code, "detail": str(exc)}
            ) from exc
        return {"entry": view.to_dict()}

    @router.delete(
        "/allowlist",
        summary="Remove a player from the allowlist",
        dependencies=[Depends(auth_guard)],
    )
    async def allowlist_remove(name: str | None = None, xuid: str | None = None) -> dict:
        if not name and not xuid:
            raise HTTPException(
                status_code=422,
                detail={"error": "bad_request", "detail": "name or xuid is required"},
            )
        try:
            removed = await _svc().allowlist_remove(name=name, xuid=xuid)
        except MaintenanceInProgressError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except UnknownPlayerError as exc:
            raise HTTPException(
                status_code=503, detail={"error": exc.code, "detail": str(exc)}
            ) from exc
        return {"removed": removed}

    @router.post(
        "/permissions",
        summary="Set a player's permission level",
        dependencies=[Depends(auth_guard)],
    )
    async def permissions_set(body: PermissionSet) -> dict:
        try:
            result = await _svc().set_permission(body.xuid, body.level)
        except PermissionRefusedError as exc:
            raise HTTPException(
                status_code=409, detail={"error": exc.code, "detail": exc.reason}
            ) from exc
        except MaintenanceInProgressError as exc:
            raise conflict(exc.code, str(exc)) from exc
        return result.to_dict()

    @router.post(
        "/enforcement",
        summary="Turn allowlist enforcement on or off",
        dependencies=[Depends(auth_guard)],
    )
    async def enforcement_set(body: EnforcementSet) -> dict:
        # Written to both masters: server.properties and the running server
        # (design.md D5). ConfigService.write persists the file and its
        # apply-enforcement hook instructs a running server.
        try:
            result = runtime.config.write({"allow-list": "true" if body.enabled else "false"})
        except MaintenanceInProgressError as exc:
            raise conflict(exc.code, str(exc)) from exc
        return {
            "ok": result.ok,
            "enforcement": runtime.config.enforcement_view().to_dict(),
        }

    return router
