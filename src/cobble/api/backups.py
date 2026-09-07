"""Backup routes: list, capture, restore (section 8, task 8.2).

Conflicting-operation rejections return a distinguishable ``error`` code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, Depends

from cobble.api._shared import auth_guard, conflict
from cobble.backup.service import BackupConflictError
from cobble.supervisor.supervisor import MaintenanceConflictError, SupervisorError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


def build_backups_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/backups", tags=["backups"], dependencies=[Depends(auth_guard)])

    @router.get("", summary="List held backups")
    async def list_backups() -> dict:
        return {
            "backups": [e.to_dict() for e in runtime.backup.list_backups()],
            "unhealthy": runtime.backup.health,
        }

    @router.post("", summary="Capture a backup now")
    async def capture() -> dict:
        try:
            outcome = await runtime.backup.capture(reason="manual")
        except BackupConflictError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except (MaintenanceConflictError, SupervisorError) as exc:
            raise conflict(getattr(exc, "code", "conflict"), str(exc)) from exc
        return outcome.to_dict()

    @router.post(
        "/{archive}/restore",
        summary="Restore a captured backup over the live installation",
    )
    async def restore(
        archive: str, confirm_old_version: bool = Body(default=False, embed=True)
    ) -> dict:
        try:
            outcome = await runtime.backup.restore(
                archive, confirm_old_version=confirm_old_version
            )
        except BackupConflictError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except (MaintenanceConflictError, SupervisorError) as exc:
            raise conflict(getattr(exc, "code", "conflict"), str(exc)) from exc
        return outcome.to_dict()

    return router
