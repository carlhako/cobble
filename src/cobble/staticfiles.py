"""Serve the compiled single-page web interface with client-side-route fallback.

A direct request to a nested interface route (e.g. ``/console`` opened or
reloaded in the browser) must return ``index.html`` so the client router can
take over, rather than a 404. Requests for files that do exist (``/assets/...``)
are served normally. Non-interface prefixes (``/api``, ``/health``, ``/docs``,
``/openapi.json``) never fall back — they keep their real 404 so a mistyped API
path is not masked by the SPA.
"""

from __future__ import annotations

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

_NON_SPA_PREFIXES = ("api/", "health", "docs", "redoc", "openapi.json")


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to ``index.html`` for unmatched client routes."""

    async def get_response(self, path: str, scope: Scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            normalised = path.lstrip("/")
            if normalised.startswith(_NON_SPA_PREFIXES):
                raise
            return await super().get_response("index.html", scope)


def static_dir() -> Path:
    """Directory holding the built frontend bundle, packaged next to this module."""
    return Path(__file__).parent / "static"


def frontend_built() -> bool:
    return (static_dir() / "index.html").is_file()
