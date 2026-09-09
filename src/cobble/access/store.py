"""Cobble's durable ban record in the shared ``cobble.db`` (server-access spec;
design.md D3).

A ban is cobble's own record, never an inference from a player's absence from the
allowlist — everyone who has never joined is also absent. One additive table,
created with ``IF NOT EXISTS`` so a second open is a no-op, alongside the player
and gamerule schemas already in the file:

* ``bans`` — one row per stable identifier: the name held at ban time, the stated
  reason, when it happened, and when it was lifted (``NULL`` while in force). The
  row is kept after a lift so the recorded name and reason stay retrievable.

Keyed by ``xuid``, so a ban survives a display-name change (task 3.4). Opened
synchronously on the event loop like the other stores — a handful of tiny rows.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from cobble.logging import get_logger

log = get_logger("access.store")


class BanStoreError(RuntimeError):
    """A ban record could not be read or written."""

    code = "ban_store_error"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS bans (
    xuid       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    banned_at  TEXT NOT NULL,
    lifted_at  TEXT
);
"""


def _iso(when: datetime | str) -> str:
    return when if isinstance(when, str) else when.isoformat()


def _fail(what: str, exc: Exception) -> NoReturn:
    raise BanStoreError(f"{what} failed: {exc}") from exc


@dataclass(frozen=True)
class BanRecord:
    xuid: str
    name: str  # the display name held at ban time
    reason: str
    banned_at: str
    lifted_at: str | None

    @property
    def active(self) -> bool:
        return self.lifted_at is None

    def to_dict(self) -> dict:
        return {
            "xuid": self.xuid,
            "name": self.name,
            "reason": self.reason,
            "banned_at": self.banned_at,
            "lifted_at": self.lifted_at,
            "active": self.active,
        }


class BanStore:
    """Synchronous handle on the ``bans`` table. Not thread-safe; used from the
    event loop only, exactly like the player and gamerule stores."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- lifecycle ----------------------------------------------
    @classmethod
    def open(cls, path: Path) -> BanStore:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise BanStoreError(f"could not open the ban record at {path}: {exc}") from exc
        return cls(conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            log.exception("closing the ban record failed")

    # -- writes -----------------------------------------------
    def record_ban(self, xuid: str, name: str, reason: str, when: datetime | str) -> None:
        """Record (or re-record) a ban for ``xuid``. Re-banning a player whose
        ban was lifted clears the lift and refreshes the name, reason, and
        time."""
        try:
            self._conn.execute(
                """
                INSERT INTO bans (xuid, name, reason, banned_at, lifted_at)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT (xuid) DO UPDATE SET
                    name = excluded.name,
                    reason = excluded.reason,
                    banned_at = excluded.banned_at,
                    lifted_at = NULL
                """,
                (xuid, name, reason or "", _iso(when)),
            )
        except sqlite3.Error as exc:
            _fail(f"recording a ban for {xuid!r}", exc)

    def lift_ban(self, xuid: str, when: datetime | str) -> bool:
        """Mark ``xuid``'s ban lifted, keeping the row so its recorded name and
        reason stay retrievable. Returns whether an active ban was lifted."""
        try:
            cur = self._conn.execute(
                "UPDATE bans SET lifted_at = ? WHERE xuid = ? AND lifted_at IS NULL",
                (_iso(when), xuid),
            )
        except sqlite3.Error as exc:
            _fail(f"lifting the ban for {xuid!r}", exc)
        return cur.rowcount > 0

    # -- reads ------------------------------------------------
    def is_banned(self, xuid: str) -> bool:
        """Whether ``xuid`` has an active ban. Absence from the allowlist is
        never consulted (design.md D3)."""
        try:
            return (
                self._conn.execute(
                    "SELECT 1 FROM bans WHERE xuid = ? AND lifted_at IS NULL", (xuid,)
                ).fetchone()
                is not None
            )
        except sqlite3.Error as exc:
            _fail(f"checking the ban for {xuid!r}", exc)

    def get(self, xuid: str) -> BanRecord | None:
        """The ban record for ``xuid`` whether active or lifted, or ``None``."""
        try:
            row = self._conn.execute(
                "SELECT xuid, name, reason, banned_at, lifted_at FROM bans WHERE xuid = ?",
                (xuid,),
            ).fetchone()
        except sqlite3.Error as exc:
            _fail(f"reading the ban for {xuid!r}", exc)
        return None if row is None else BanRecord(*row)

    def active_bans(self) -> list[BanRecord]:
        try:
            rows = self._conn.execute(
                """
                SELECT xuid, name, reason, banned_at, lifted_at
                  FROM bans WHERE lifted_at IS NULL
                 ORDER BY banned_at DESC
                """
            ).fetchall()
        except sqlite3.Error as exc:
            _fail("reading active bans", exc)
        return [BanRecord(*r) for r in rows]

    def all_bans(self) -> list[BanRecord]:
        try:
            rows = self._conn.execute(
                """
                SELECT xuid, name, reason, banned_at, lifted_at
                  FROM bans ORDER BY banned_at DESC
                """
            ).fetchall()
        except sqlite3.Error as exc:
            _fail("reading all bans", exc)
        return [BanRecord(*r) for r in rows]

    def count_active(self) -> int:
        try:
            row = self._conn.execute("SELECT COUNT(*) FROM bans WHERE lifted_at IS NULL").fetchone()
        except sqlite3.Error as exc:
            _fail("counting active bans", exc)
        return int(row[0]) if row else 0


def open_ban_store(path: Path) -> BanStore:
    """Open (creating if absent) the ``bans`` table in the database at ``path``."""
    return BanStore.open(path)
