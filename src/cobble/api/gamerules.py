"""Gamerule routes (server-gamerules spec, section 5).

* ``GET  /api/gamerules``            — the active world's set with its liveness
* ``POST /api/gamerules``            — write one rule (or queue it while stopped)
* ``GET  /api/gamerules/defaults``   — the operator's preferred defaults
* ``PUT  /api/gamerules/defaults``   — set one preferred default
* ``DELETE /api/gamerules/defaults/{name}`` — clear one preferred default
* ``POST /api/gamerules/acknowledge`` — dismiss an adoption / repair / defaults report

The state-changing routes depend on ``auth_guard`` exactly like the other
state-changing routers (design.md D8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cobble.api._shared import auth_guard, conflict
from cobble.gamerules.catalogue import CATALOGUE, lookup
from cobble.gamerules.manager import GameruleView
from cobble.gamerules.parser import ParsedRule
from cobble.gamerules.service import GameruleRefusedError, GameruleUnavailableError
from cobble.gamerules.storage import GameruleStorageError
from cobble.supervisor.supervisor import MaintenanceInProgressError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


class RuleWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    value: bool | int | str


class DefaultWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    value: bool | int | str


def _rule_json(pr: ParsedRule) -> dict:
    out = pr.to_dict()
    cat = lookup(pr.name)
    if cat is not None:
        out.update(
            {
                "minimum": cat.minimum,
                "maximum": cat.maximum,
                "members": list(cat.members),
                "description": cat.description,
                "default": cat.default,
            }
        )
    return out


def _view_json(view: GameruleView) -> dict:
    return {
        "level_name": view.level_name,
        "liveness": view.liveness.value,
        "sampled_at": view.sampled_at,
        "rules": [_rule_json(r) for r in view.rules],
        "report": view.report.to_dict() if view.report is not None else None,
    }


def build_gamerules_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/gamerules", tags=["gamerules"])

    def _manager():
        mgr = getattr(runtime, "gamerules", None)
        if mgr is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "gamerules_unavailable",
                    "detail": "gamerule storage could not be opened",
                },
            )
        return mgr

    @router.get("", summary="The active world's gamerule set")
    async def read() -> dict:
        try:
            view = await _manager().current_view()
        except GameruleStorageError as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": exc.code, "detail": str(exc)},
            ) from exc
        return _view_json(view)

    @router.post(
        "",
        summary="Write one gamerule (queued while the server is stopped)",
        dependencies=[Depends(auth_guard)],
    )
    async def write(body: RuleWrite) -> dict:
        mgr = _manager()
        try:
            result = await mgr.write_rule(body.name, body.value)
        except GameruleRefusedError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": exc.code, "rule": exc.rule, "detail": exc.reason},
            ) from exc
        except MaintenanceInProgressError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except GameruleUnavailableError as exc:
            raise HTTPException(
                status_code=503, detail={"error": exc.code, "detail": str(exc)}
            ) from exc
        if result.queued:
            return {
                "queued": True,
                "level_name": result.level_name,
                "pending": result.pending,
                "detail": "the server is not running; this will be applied at the next start",
            }
        assert result.rules is not None
        applied = result.rules.get(body.name)
        return {
            "queued": False,
            "level_name": result.level_name,
            "rule": _rule_json(applied) if applied is not None else None,
            "rules": [_rule_json(r) for r in result.rules],
        }

    @router.get("/defaults", summary="The operator's preferred gamerule defaults")
    async def read_defaults() -> dict:
        return {
            "defaults": _manager().read_defaults(),
            "catalogue": [rule.to_dict() for rule in CATALOGUE],
        }

    @router.put(
        "/defaults",
        summary="Set one preferred default",
        dependencies=[Depends(auth_guard)],
    )
    async def set_default(body: DefaultWrite) -> dict:
        try:
            defaults = _manager().set_default(body.name, body.value)
        except GameruleRefusedError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": exc.code, "rule": exc.rule, "detail": exc.reason},
            ) from exc
        except GameruleStorageError as exc:
            raise HTTPException(
                status_code=503, detail={"error": exc.code, "detail": str(exc)}
            ) from exc
        return {"defaults": defaults}

    @router.delete(
        "/defaults/{name}",
        summary="Clear one preferred default",
        dependencies=[Depends(auth_guard)],
    )
    async def clear_default(name: str) -> dict:
        try:
            defaults = _manager().clear_default(name)
        except GameruleStorageError as exc:
            raise HTTPException(
                status_code=503, detail={"error": exc.code, "detail": str(exc)}
            ) from exc
        return {"defaults": defaults}

    @router.post(
        "/acknowledge",
        summary="Dismiss an adoption / repair / defaults report",
        dependencies=[Depends(auth_guard)],
    )
    async def acknowledge() -> dict:
        mgr = _manager()
        try:
            mgr.acknowledge_report(mgr.active_world())
        except GameruleStorageError as exc:
            raise HTTPException(
                status_code=503, detail={"error": exc.code, "detail": str(exc)}
            ) from exc
        return {"ok": True}

    return router
