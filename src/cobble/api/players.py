"""Player roster routes (server-players spec, section 6) plus the moderation
routes M6 adds (kick, ban, unban — section 7.3).

The roster reads are unauthenticated like ``/api/status``. The moderation routes
change state and depend on ``auth_guard`` like every other state-changing route
(design.md D8). A database that could not be opened at startup is surfaced here
as a 503 rather than an empty roster.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cobble.access.service import NotConnectedError, UnknownPlayerError
from cobble.api._shared import auth_guard, conflict
from cobble.players.storage import PlayerStore, RosterEntry, SessionRow
from cobble.supervisor.supervisor import MaintenanceInProgressError, NotRunningError

if TYPE_CHECKING:
    from cobble.runtime import Runtime


class KickBody(BaseModel):
    reason: str = Field(default="", max_length=200)


class BanBody(BaseModel):
    reason: str = Field(default="", max_length=200)
    confirm: bool = False
    permit_excluded: bool = False


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

    def _require_player(xuid: str) -> str:
        """The current display name for ``xuid``, or a 404 if cobble has no
        recorded session for that identifier (task 7.3)."""
        store = _store()
        if not store.player_exists(xuid):
            raise HTTPException(
                status_code=404,
                detail={"error": "unknown_player", "detail": f"no player {xuid!r} on record"},
            )
        return runtime._roster_names().get(xuid, xuid)

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

    # -- moderation (section 7.3) ---------------------------------
    @router.post(
        "/{xuid}/kick",
        summary="Disconnect a connected player",
        dependencies=[Depends(auth_guard)],
    )
    async def kick(xuid: str, body: KickBody) -> dict:
        name = _require_player(xuid)
        try:
            result = await runtime.access.kick(xuid, name, body.reason)
        except NotRunningError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except NotConnectedError as exc:
            raise conflict(exc.code, str(exc)) from exc
        return result.to_dict()

    @router.post(
        "/{xuid}/ban",
        summary="Ban a player (composite: allowlist, enforcement, kick, record)",
        dependencies=[Depends(auth_guard)],
    )
    async def ban(xuid: str, body: BanBody) -> dict:
        _require_player(xuid)
        try:
            result = await runtime.access.ban(
                xuid, body.reason, confirm=body.confirm, permit_excluded=body.permit_excluded
            )
        except MaintenanceInProgressError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except UnknownPlayerError as exc:
            raise HTTPException(
                status_code=404, detail={"error": exc.code, "detail": str(exc)}
            ) from exc
        if result.needs_confirmation:
            # The exclusion preview, not the ban (task 7.5).
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "confirmation_required",
                    "detail": "enabling allowlist enforcement would exclude other players",
                    "would_exclude": list(result.would_exclude),
                },
            )
        return result.to_dict()

    @router.post(
        "/{xuid}/unban",
        summary="Lift a recorded ban",
        dependencies=[Depends(auth_guard)],
    )
    async def unban(xuid: str) -> dict:
        try:
            result = await runtime.access.unban(xuid)
        except MaintenanceInProgressError as exc:
            raise conflict(exc.code, str(exc)) from exc
        except UnknownPlayerError as exc:
            raise HTTPException(
                status_code=404, detail={"error": exc.code, "detail": str(exc)}
            ) from exc
        return result.to_dict()

    return router
