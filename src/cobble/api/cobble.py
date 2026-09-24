"""cobble's own version, release check, and upgrade routes (cobble-self-update
spec; design.md D7).

Registered under the single ``/api`` router with the shared ``auth_guard``.
The upgrade route only *requests* an upgrade: the root helper installs it and
restarts cobble (design.md D2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, Depends

from cobble.api._shared import auth_guard, conflict
from cobble.selfupdate.upgrade import UpgradeError, manual_command
from cobble.supervisor.supervisor import SupervisorError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


def build_cobble_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/cobble", tags=["cobble"], dependencies=[Depends(auth_guard)])

    def version_view() -> dict:
        one_click = runtime.upgrade.helper_installed()
        return {
            **runtime.release_check.view(),
            "one_click_available": one_click,
            "manual_command": None if one_click else manual_command(runtime.settings),
            "upgrade": runtime.upgrade.view(),
        }

    @router.get("/version", summary="Running cobble version, release check, and upgrade state")
    async def version() -> dict:
        return version_view()

    @router.post("/check", summary="Check GitHub for a newer cobble release now")
    async def check() -> dict:
        await runtime.release_check.check()
        return version_view()

    @router.post("/upgrade", summary="Upgrade cobble to the available release")
    async def upgrade(version: str = Body(..., embed=True)) -> dict:
        try:
            await runtime.upgrade.request(version)
        except UpgradeError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except SupervisorError as exc:
            raise conflict(getattr(exc, "code", "conflict"), str(exc)) from exc
        return version_view()

    return router
