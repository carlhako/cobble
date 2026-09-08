"""Player roster routes (server-players spec, section 6).

Read-only, and unauthenticated like ``/api/status`` — this change adds no
state-changing route, so nothing here depends on ``auth_guard`` (design.md D8;
task 6.4). A database that could not be opened at startup is surfaced here as a
503 rather than an empty roster.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from cobble.players.storage import PlayerStore, RosterEntry, SessionRow

if TYPE_CHECKING:
    from cobble.runtime import Runtime


def _entry_json(e: RosterEntry) -> dict:
    return {
        "xuid": e.xuid,
        "gamertag": e.gamertag,
        "total_playtime_seconds": e.total_seconds,
        "session_count": e.session_count,
        "first_seen": e.first_seen,
        "last_seen": e.last_seen,
        "online": e.online,
        "approximate": e.approximate,
    }


def _session_json(s: SessionRow) -> dict:
    return {
        "connected_at": s.connected_at,
        "spawned_at": s.spawned_at,
        "disconnected_at": s.disconnected_at,
        "duration_seconds": s.duration_seconds,
        "end_reason": s.end_reason,
        "in_progress": s.in_progress,
        "approximate": s.approximate,
    }


def build_players_router(runtime: Runtime) -> APIRouter:
    router = APIRouter(prefix="/players", tags=["players"])

    def _store() -> PlayerStore:
        if runtime.players is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "player_history_unavailable",
                    "detail": "player history could not be opened; the roster is not recording",
                },
            )
        return runtime.players

    @router.get("", summary="The player roster")
    async def roster() -> dict:
        store = _store()
        now = datetime.now(UTC)
        return {
            "players": [_entry_json(e) for e in store.roster(now=now)],
            "recorded_since": store.recorded_since(),
        }

    @router.get("/{xuid}/sessions", summary="One player's session history")
    async def sessions(xuid: str) -> dict:
        store = _store()
        now = datetime.now(UTC)
        try:
            rows = store.sessions_for(xuid, now=now)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": "unknown_player", "detail": f"no player {xuid!r} on record"},
            ) from exc
        return {
            "xuid": xuid,
            "gamertag": rows[0].gamertag if rows else "",
            "sessions": [_session_json(s) for s in rows],
        }

    return router
