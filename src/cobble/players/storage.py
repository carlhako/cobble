"""SQLite-backed player history storage (server-players spec; design.md D5, D8, D9).

Opened synchronously on the event loop: writes are a handful of rows per hour and
reads are sub-millisecond aggregations at family scale, so an async driver would
buy nothing (design.md D5). WAL mode keeps the writer from blocking readers and
makes the pre-backup checkpoint (D6) a meaningful operation.

Schema (design.md D8):

* ``players`` — one row per stable identifier (``xuid``), carrying the most
  recently observed display name for search and display.
* ``sessions`` — one row per observed connection: the connect, world-entry and
  departure times recorded independently (D2), the per-session display name so a
  rename does not rewrite history, how the session ended (``end_reason``), and
  the last time the session was known to be active (the tier-3 checkpoint, D1).

Totals (playtime, session count) are computed by aggregation, never stored, so
they cannot drift from the sessions that back them (D9).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cobble.logging import get_logger

log = get_logger("players.storage")

SCHEMA_VERSION = 1
DB_FILENAME = "cobble.db"

# How a session ended. A reconstructed end was inferred on the next startup
# rather than observed, and is reported as approximate everywhere (D1).
END_OBSERVED = "observed"
END_SERVER_STOP = "server_stop"
END_SERVER_EXIT = "server_exit"
END_RECONSTRUCTED = "reconstructed"

APPROXIMATE_END_REASONS: frozenset[str] = frozenset({END_RECONSTRUCTED})


class PlayerHistoryError(RuntimeError):
    """Player history could not be opened or brought to a consistent form."""

    code = "player_history_error"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    xuid       TEXT PRIMARY KEY,
    gamertag   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    xuid            TEXT NOT NULL REFERENCES players (xuid),
    gamertag        TEXT NOT NULL,
    connected_at    TEXT NOT NULL,
    spawned_at      TEXT,
    disconnected_at TEXT,
    end_reason      TEXT,
    last_active_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_xuid ON sessions (xuid);
CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions (xuid) WHERE end_reason IS NULL;
"""


@dataclass(frozen=True)
class RosterEntry:
    xuid: str
    gamertag: str
    total_seconds: float
    session_count: int
    first_seen: str
    last_seen: str
    online: bool
    approximate: bool


@dataclass(frozen=True)
class SessionRow:
    id: int
    xuid: str
    gamertag: str
    connected_at: str
    spawned_at: str | None
    disconnected_at: str | None
    end_reason: str | None
    last_active_at: str
    duration_seconds: float
    in_progress: bool
    approximate: bool


def _iso(when: datetime | str) -> str:
    return when if isinstance(when, str) else when.isoformat()


def _span_seconds(start: str, end: str) -> float:
    try:
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    except ValueError:
        return 0.0
    return max(0.0, delta.total_seconds())


class PlayerStore:
    """Synchronous handle on the player-history database. Not thread-safe: it is
    used from the event loop thread only. The pre-backup checkpoint uses a
    separate short-lived connection (:func:`quiesce_database`)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- lifecycle ------------------------------------------------
    @classmethod
    def open(cls, path: Path) -> PlayerStore:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # check_same_thread=False: the store is only ever touched from the
            # event loop (route handlers, the recorder callback and the
            # checkpoint task all run there, cooperatively, and sqlite calls
            # don't yield mid-call), but the object may be *constructed* on a
            # different thread than the loop runs on (e.g. under the test
            # client). No concurrent use crosses threads.
            conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise PlayerHistoryError(f"could not open player history at {path}: {exc}") from exc
        store = cls(conn)
        try:
            store._check_schema_version()
        except Exception:
            store.close()
            raise
        return store

    def _check_schema_version(self) -> None:
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            return
        found = int(row[0])
        if found > SCHEMA_VERSION:
            raise PlayerHistoryError(
                f"player history schema version {found} is newer than this cobble "
                f"supports ({SCHEMA_VERSION}); refusing to use it"
            )
        if found < SCHEMA_VERSION:
            raise PlayerHistoryError(
                f"player history schema version {found} is older than expected "
                f"({SCHEMA_VERSION}) and no migration is defined"
            )

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            log.exception("closing player history failed")

    # -- writes -------------------------------------------------
    def _upsert_player(self, xuid: str, gamertag: str, when: str) -> None:
        self._conn.execute(
            """
            INSERT INTO players (xuid, gamertag, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (xuid) DO UPDATE SET gamertag = excluded.gamertag,
                                             updated_at = excluded.updated_at
            """,
            (xuid, gamertag, when),
        )

    def open_session(self, xuid: str, gamertag: str, when: datetime | str) -> int:
        """Record a new open session for ``xuid``. A reconnect always starts a
        fresh session — no merging with a prior one (D4)."""
        ts = _iso(when)
        with self._conn:
            self._upsert_player(xuid, gamertag, ts)
            cur = self._conn.execute(
                """
                INSERT INTO sessions
                    (xuid, gamertag, connected_at, last_active_at)
                VALUES (?, ?, ?, ?)
                """,
                (xuid, gamertag, ts, ts),
            )
        return int(cur.lastrowid)

    def record_spawn(self, xuid: str, when: datetime | str) -> None:
        """Record world entry on the player's open session, first-write-wins: a
        later world entry within the same session leaves the first intact (D3)."""
        ts = _iso(when)
        with self._conn:
            self._conn.execute(
                """
                UPDATE sessions SET spawned_at = ?, last_active_at = ?
                WHERE xuid = ? AND end_reason IS NULL AND spawned_at IS NULL
                """,
                (ts, ts, xuid),
            )
            self._conn.execute(
                "UPDATE sessions SET last_active_at = ? WHERE xuid = ? AND end_reason IS NULL",
                (ts, xuid),
            )

    def close_session(self, xuid: str, when: datetime | str, reason: str) -> int:
        """Close the player's open session at ``when`` with ``reason``. Returns
        the number of sessions closed (0 if none was open)."""
        ts = _iso(when)
        with self._conn:
            cur = self._conn.execute(
                """
                UPDATE sessions
                   SET disconnected_at = ?, end_reason = ?, last_active_at = ?
                 WHERE xuid = ? AND end_reason IS NULL
                """,
                (ts, reason, ts, xuid),
            )
        return cur.rowcount

    def close_all_open(self, when: datetime | str, reason: str) -> int:
        """Close every open session at ``when`` with ``reason`` (D1 tiers 1/2)."""
        ts = _iso(when)
        with self._conn:
            cur = self._conn.execute(
                """
                UPDATE sessions
                   SET disconnected_at = ?, end_reason = ?, last_active_at = ?
                 WHERE end_reason IS NULL
                """,
                (ts, reason, ts),
            )
        return cur.rowcount

    def touch_open_sessions(self, when: datetime | str) -> int:
        """Advance the last-known-active time of every open session (the tier-3
        checkpoint, D1). Returns the number of sessions touched."""
        ts = _iso(when)
        with self._conn:
            cur = self._conn.execute(
                "UPDATE sessions SET last_active_at = ? WHERE end_reason IS NULL",
                (ts,),
            )
        return cur.rowcount

    def reconcile_open_sessions(
        self,
        *,
        shutdown_at: datetime | str | None = None,
        reason: str = END_RECONSTRUCTED,
        xuid: str | None = None,
    ) -> int:
        """Close any session left open by a previous run (D1 tier 3), at a time
        no later than the last point it was known active. If a shutdown time is
        recorded and it is later than that, prefer it (task 4.3). Pass ``xuid``
        to reconcile just that player's stale session. Returns the number of
        sessions reconciled."""
        shutdown = _iso(shutdown_at) if shutdown_at is not None else None
        with self._conn:
            cur = self._conn.execute(
                """
                UPDATE sessions
                   SET disconnected_at = CASE
                           WHEN ?1 IS NOT NULL AND ?1 > last_active_at THEN ?1
                           ELSE last_active_at
                       END,
                       end_reason = ?2
                 WHERE end_reason IS NULL AND (?3 IS NULL OR xuid = ?3)
                """,
                (shutdown, reason, xuid),
            )
        return cur.rowcount

    # -- reads --------------------------------------------------
    def player_exists(self, xuid: str) -> bool:
        return (
            self._conn.execute("SELECT 1 FROM players WHERE xuid = ?", (xuid,)).fetchone()
            is not None
        )

    def has_open_session(self, xuid: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM sessions WHERE xuid = ? AND end_reason IS NULL", (xuid,)
            ).fetchone()
            is not None
        )

    def open_session_xuids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT xuid FROM sessions WHERE end_reason IS NULL ORDER BY xuid"
        ).fetchall()
        return [r[0] for r in rows]

    def recorded_since(self) -> str | None:
        row = self._conn.execute("SELECT MIN(connected_at) FROM sessions").fetchone()
        return row[0] if row and row[0] is not None else None

    def roster(self, now: datetime | str) -> list[RosterEntry]:
        """Every observed player with total playtime, session count, first/last
        seen, and whether they are currently online. Totals are the sum of
        session durations (D9); an open session contributes its elapsed time."""
        ref = _iso(now)
        rows = self._conn.execute(
            """
            SELECT s.xuid, p.gamertag, s.connected_at, s.disconnected_at,
                   s.end_reason, s.last_active_at
              FROM sessions s
              JOIN players p ON p.xuid = s.xuid
            """
        ).fetchall()
        by_player: dict[str, dict] = {}
        for xuid, gamertag, connected_at, disconnected_at, end_reason, _last in rows:
            agg = by_player.setdefault(
                xuid,
                {
                    "gamertag": gamertag,
                    "total": 0.0,
                    "count": 0,
                    "first_seen": connected_at,
                    "last_seen": connected_at,
                    "online": False,
                    "approximate": False,
                },
            )
            end = disconnected_at or ref
            agg["total"] += _span_seconds(connected_at, end)
            agg["count"] += 1
            agg["first_seen"] = min(agg["first_seen"], connected_at)
            agg["last_seen"] = max(agg["last_seen"], end)
            if end_reason is None:
                agg["online"] = True
            if end_reason in APPROXIMATE_END_REASONS:
                agg["approximate"] = True
        entries = [
            RosterEntry(
                xuid=xuid,
                gamertag=agg["gamertag"],
                total_seconds=agg["total"],
                session_count=agg["count"],
                first_seen=agg["first_seen"],
                last_seen=agg["last_seen"],
                online=agg["online"],
                approximate=agg["approximate"],
            )
            for xuid, agg in by_player.items()
        ]
        entries.sort(key=lambda e: e.last_seen, reverse=True)
        return entries

    def sessions_for(self, xuid: str, now: datetime | str) -> list[SessionRow]:
        """The player's sessions, most recent first (task 6.2). Raises
        :class:`KeyError` if the identifier is not a known player."""
        if not self.player_exists(xuid):
            raise KeyError(xuid)
        ref = _iso(now)
        rows = self._conn.execute(
            """
            SELECT id, xuid, gamertag, connected_at, spawned_at, disconnected_at,
                   end_reason, last_active_at
              FROM sessions
             WHERE xuid = ?
             ORDER BY connected_at DESC, id DESC
            """,
            (xuid,),
        ).fetchall()
        out: list[SessionRow] = []
        for (
            sid,
            row_xuid,
            gamertag,
            connected_at,
            spawned_at,
            disconnected_at,
            end_reason,
            last_active_at,
        ) in rows:
            end = disconnected_at or ref
            out.append(
                SessionRow(
                    id=sid,
                    xuid=row_xuid,
                    gamertag=gamertag,
                    connected_at=connected_at,
                    spawned_at=spawned_at,
                    disconnected_at=disconnected_at,
                    end_reason=end_reason,
                    last_active_at=last_active_at,
                    duration_seconds=_span_seconds(connected_at, end),
                    in_progress=end_reason is None,
                    approximate=end_reason in APPROXIMATE_END_REASONS,
                )
            )
        return out

    # -- backup quiesce (D6) ------------------------------------
    def quiesce(self) -> None:
        """Checkpoint and truncate the WAL so the main file is self-contained
        and the sidecars are empty. Raises :class:`PlayerHistoryError` if the
        checkpoint cannot complete."""
        _run_truncating_checkpoint(self._conn)


def open_store(path: Path) -> PlayerStore:
    """Open (creating if absent) the player-history database at ``path``."""
    return PlayerStore.open(path)


def _run_truncating_checkpoint(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    # (busy, log_frames, checkpointed_frames); busy != 0 means the checkpoint
    # could not run to completion because another connection held the database.
    if row is not None and row[0] != 0:
        raise PlayerHistoryError(
            "could not checkpoint the player-history WAL: the database is busy"
        )


def quiesce_database(path: Path) -> None:
    """Bring the player-history database at ``path`` to a self-contained,
    restorable form before a backup captures it (D6). A missing database is a
    no-op. Uses its own connection so it is safe to call from the capture
    thread. Raises :class:`PlayerHistoryError` on failure."""
    if not path.exists():
        return
    try:
        conn = sqlite3.connect(str(path), isolation_level=None)
    except sqlite3.Error as exc:
        raise PlayerHistoryError(f"could not open {path} to quiesce it: {exc}") from exc
    try:
        _run_truncating_checkpoint(conn)
    except sqlite3.Error as exc:
        raise PlayerHistoryError(f"could not quiesce {path}: {exc}") from exc
    finally:
        conn.close()
