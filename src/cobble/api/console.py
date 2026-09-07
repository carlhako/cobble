"""Console routes: the output stream (SSE) and command submission."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from cobble.api._shared import auth_guard, http_error_from_supervisor, sse_response
from cobble.console.buffer import ConsoleLine
from cobble.supervisor.supervisor import SupervisorError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)


def _line_json(line: ConsoleLine) -> dict:
    return {"seq": line.seq, "kind": line.kind.value, "text": line.text}


def build_console_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/console", tags=["console"])

    @router.get("/stream", summary="Stream console output (SSE)")
    async def stream(request: Request):
        async def lines():
            async for line in runtime.console.stream():
                yield _line_json(line)

        return sse_response(lines(), request)

    @router.post(
        "/command",
        status_code=204,
        summary="Submit a console command",
        dependencies=[Depends(auth_guard)],
    )
    async def command(body: CommandRequest) -> None:
        try:
            await runtime.console.submit_command(body.command)
        except SupervisorError as exc:
            raise http_error_from_supervisor(exc) from exc

    return router
