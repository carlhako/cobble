"""Configuration routes: read the settings and their schema, write a batch of
changes, and list the worlds that back ``level-name`` (server-config spec, M3).

Registered under the single ``/api`` router with the shared ``auth_guard``, like
every other state-changing route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cobble.api._shared import auth_guard, conflict
from cobble.supervisor.supervisor import MaintenanceInProgressError, SupervisorError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


class ConfigWriteRequest(BaseModel):
    changes: dict[str, str]


def build_config_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(auth_guard)])

    @router.get("", summary="Read server.properties as typed settings")
    async def read() -> dict:
        cfg = runtime.config
        return {
            "settings": [s.to_dict() for s in cfg.read()],
            "pending": [c.to_dict() for c in cfg.pending()],
        }

    @router.post("", summary="Write a batch of configuration changes")
    async def write(body: ConfigWriteRequest) -> dict:
        try:
            result = runtime.config.write(body.changes)
        except MaintenanceInProgressError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except SupervisorError as exc:  # defensive: any other lifecycle rejection
            raise conflict(getattr(exc, "code", "conflict"), str(exc)) from exc
        return result.to_dict()

    @router.get("/worlds", summary="List the worlds backing level-name")
    async def worlds() -> dict:
        return runtime.config.worlds().to_dict()

    return router
