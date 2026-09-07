"""Status routes: current status and the status change stream (SSE)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from cobble.api._shared import sse_response

if TYPE_CHECKING:
    from cobble.runtime import Runtime


def build_status_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/status", tags=["status"])

    @router.get("", summary="Current server status")
    async def status() -> dict:
        return runtime.status.snapshot().to_dict()

    @router.get("/stream", summary="Stream status changes (SSE)")
    async def status_stream(request: Request):
        async def snapshots():
            async for snap in runtime.status.stream():
                yield snap.to_dict()

        return sse_response(snapshots(), request)

    return router
