"""Maintenance settings routes: read the effective settings, write a batch of
changes (maintenance-settings spec; tasks 5.1, 5.2).

Registered under the single ``/api`` router with the shared ``auth_guard``,
like every other state-changing route (design.md D8).

Unlike ``server-config``'s write path, a maintenance-settings write is **not**
refused while a backup/update/restore is in progress. ``server-config``
refuses writes during maintenance because some of its settings (``allow-list``)
are pushed live to the running server and a config snapshot is taken for the
"pending" comparison — both of which are only meaningful relative to a
lifecycle in a settled state. The maintenance-settings overlay touches none of
that: it is cobble's own state, read only by the scheduler (for its next wake)
and by ``BackupService`` (for the next prune), never by the running Bedrock
process. Saving a new retention count or schedule while, say, a scheduled
backup is in flight changes nothing about that in-flight operation and cannot
race it, so there is no consistency reason to refuse it (see task 5.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cobble.api._shared import auth_guard

if TYPE_CHECKING:
    from cobble.runtime import Runtime


class MaintenanceSettingsWriteRequest(BaseModel):
    changes: dict


def build_maintenance_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(
        prefix="/maintenance", tags=["maintenance"], dependencies=[Depends(auth_guard)]
    )

    @router.get("/settings", summary="Read the effective maintenance settings")
    async def read() -> dict:
        return runtime.maintenance_settings.effective_view().to_dict()

    @router.post("/settings", summary="Write a batch of maintenance settings changes")
    async def write(body: MaintenanceSettingsWriteRequest) -> dict:
        result = runtime.maintenance_settings.write(body.changes)
        return result.to_dict()

    return router
