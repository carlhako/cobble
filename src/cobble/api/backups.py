"""Backup routes: list, capture, restore (section 8, task 8.2).

Conflicting-operation rejections return a distinguishable ``error`` code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse

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

    @router.get("/{archive}", summary="Download a held backup archive")
    async def download(archive: str) -> FileResponse:
        # The name must be a bare filename that resolves to a held backup; a
        # name with path separators or one that escapes the backup directory is
        # refused rather than followed (server-backups: a held backup can be
        # retrieved as a single file).
        store = runtime.backup.store
        if "/" in archive or "\\" in archive or archive in ("", ".", ".."):
            raise HTTPException(status_code=404, detail={"error": "not_found", "detail": archive})
        entry = store.get(archive)
        if entry is None or not entry.archive.is_file():
            raise HTTPException(status_code=404, detail={"error": "not_found", "detail": archive})
        resolved = entry.archive.resolve()
        if resolved.parent != store.dir.resolve():
            raise HTTPException(status_code=404, detail={"error": "not_found", "detail": archive})
        # A backup that failed verification is still served for inspection.
        return FileResponse(
            resolved,
            media_type="application/gzip",
            filename=entry.archive.name,
            content_disposition_type="attachment",
        )

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
            outcome = await runtime.backup.restore(archive, confirm_old_version=confirm_old_version)
        except BackupConflictError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except (MaintenanceConflictError, SupervisorError) as exc:
            raise conflict(getattr(exc, "code", "conflict"), str(exc)) from exc
        return outcome.to_dict()

    return router
