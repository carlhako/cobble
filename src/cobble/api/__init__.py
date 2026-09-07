"""HTTP interface (section 7).

All state-changing routes are registered under a single router with one
dependency-injection point (``auth_guard``) so authentication can later be added
as an insertion rather than a rewrite (design.md D8). The web interface uses
exactly these routes — it has no privileged path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from cobble.runtime import Runtime

__all__ = ["build_api_router"]


def build_api_router(runtime: Runtime) -> APIRouter:
    from cobble.api.backups import build_backups_router
    from cobble.api.console import build_console_router
    from cobble.api.lifecycle import build_lifecycle_router
    from cobble.api.status import build_status_router
    from cobble.api.updates import build_updates_router

    router = APIRouter(prefix="/api")
    router.include_router(build_lifecycle_router(runtime))
    router.include_router(build_console_router(runtime))
    router.include_router(build_status_router(runtime))
    router.include_router(build_updates_router(runtime))
    router.include_router(build_backups_router(runtime))
    return router
