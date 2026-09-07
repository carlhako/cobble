"""Shared API helpers: the auth seam, structured errors, and SSE plumbing."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse

from cobble.supervisor.supervisor import SupervisorError


async def auth_guard() -> None:
    """The single dependency-injection point for authentication (design.md D8).

    v1 is LAN-only and unauthenticated, so this is a no-op. Adding auth later is
    an edit to this one function — every state-changing route already depends on
    it.
    """
    return None


def http_error_from_supervisor(exc: SupervisorError) -> HTTPException:
    """Map a lifecycle error to a 409 with a distinguishable ``error`` code."""
    return HTTPException(
        status_code=409,
        detail={"error": exc.code, "detail": str(exc)},
    )


def conflict(code: str, detail: str) -> HTTPException:
    """A 409 carrying a distinguishable ``error`` code (server-backups /
    server-updates: conflicting-operation errors)."""
    return HTTPException(status_code=409, detail={"error": code, "detail": detail})


def sse_response(
    events: AsyncIterator,
    request: Request,
    *,
    serialize: Callable[[object], str] | None = None,
) -> StreamingResponse:
    dump = serialize or (lambda obj: json.dumps(obj))

    async def body() -> AsyncIterator[bytes]:
        # Prelude so proxies flush headers immediately.
        yield b": connected\n\n"
        try:
            async for event in events:
                if await request.is_disconnected():
                    break
                yield f"data: {dump(event)}\n\n".encode()
        except (ConnectionResetError, RuntimeError):
            return

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
