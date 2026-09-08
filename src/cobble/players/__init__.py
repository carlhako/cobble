"""Durable player identity and session history (server-players spec, M4).

Cobble has parsed player connect/spawn/disconnect events since M1 and never
written one down. This package is the durable consumer: a SQLite database at
``<state_dir>/cobble.db`` (the path M1's design reserved) recording every
observed player session, an event-bus subscriber that fills it, and the queries
the roster is built from.
"""

from __future__ import annotations

from cobble.players.recorder import SessionRecorder
from cobble.players.service import PlayerHistoryService
from cobble.players.storage import (
    APPROXIMATE_END_REASONS,
    DB_FILENAME,
    END_OBSERVED,
    END_RECONSTRUCTED,
    END_SERVER_EXIT,
    END_SERVER_STOP,
    SCHEMA_VERSION,
    PlayerHistoryError,
    PlayerStore,
    RosterEntry,
    SessionRow,
    open_store,
    quiesce_database,
)

__all__ = [
    "APPROXIMATE_END_REASONS",
    "DB_FILENAME",
    "END_OBSERVED",
    "END_RECONSTRUCTED",
    "END_SERVER_EXIT",
    "END_SERVER_STOP",
    "SCHEMA_VERSION",
    "PlayerHistoryError",
    "PlayerHistoryService",
    "PlayerStore",
    "RosterEntry",
    "SessionRecorder",
    "SessionRow",
    "open_store",
    "quiesce_database",
]
