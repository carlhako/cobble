"""Per-world gamerule records in the shared ``cobble.db`` (server-gamerules spec;
design.md D8).

Four tables, all additive to M4's schema and created with ``IF NOT EXISTS`` so a
second open is a no-op:

* ``gamerule_records`` — one row per world (keyed by ``level-name``): the sampled
  rule set as JSON and the time it was taken.
* ``gamerule_defaults`` — the operator's preferred values, world-independent, one
  row per rule so a single preference can be cleared on its own.
* ``gamerule_restore_marker`` — at most one row, naming the world a restore just
  replaced, consumed by the next readiness (design.md D6).
* ``gamerule_reports`` — one unacknowledged report per world (adoption, repair,
  or first-sight defaults), replaced when a newer one is recorded and removed
  when the operator acknowledges it.

Opened on the event loop like the player store: a handful of tiny rows, no async
driver needed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from cobble.logging import get_logger

log = get_logger("gamerules.storage")

RuleValue = bool | int | str

# report kinds
REPORT_ADOPTION = "adoption"
REPORT_REPAIR = "repair"
REPORT_DEFAULTS = "defaults"


class GameruleStorageError(RuntimeError):
    """A gamerule record could not be read or written."""

    code = "gamerule_storage_error"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS gamerule_records (
    level_name  TEXT PRIMARY KEY,
    sampled_at  TEXT NOT NULL,
    rules_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gamerule_defaults (
    name        TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gamerule_restore_marker (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    level_name  TEXT NOT NULL,
    set_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gamerule_reports (
    level_name   TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    rules_json   TEXT NOT NULL
);

-- Writes an operator submitted while the server was stopped: the intended value
-- for that world, applied at the next start (server-gamerules spec; task 5.5).
CREATE TABLE IF NOT EXISTS gamerule_pending (
    level_name  TEXT NOT NULL,
    name        TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    PRIMARY KEY (level_name, name)
);
"""


def _iso(when: datetime | str) -> str:
    return when if isinstance(when, str) else when.isoformat()


def _fail(what: str, exc: Exception) -> NoReturn:
    raise GameruleStorageError(f"{what} failed: {exc}") from exc


@dataclass(frozen=True)
class WorldRecord:
    level_name: str
    sampled_at: str
    values: dict[str, RuleValue]


@dataclass(frozen=True)
class Report:
    level_name: str
    kind: str  # REPORT_ADOPTION | REPORT_REPAIR | REPORT_DEFAULTS
    created_at: str
    rules: dict[str, RuleValue]  # rule -> value adopted / re-applied / set

    def to_dict(self) -> dict:
        return {
            "level_name": self.level_name,
            "kind": self.kind,
            "created_at": self.created_at,
            "rules": self.rules,
        }


class GameruleStore:
    """Synchronous handle on the gamerule tables. Not thread-safe; used from the
    event loop only, exactly like :class:`cobble.players.storage.PlayerStore`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- lifecycle -------------------------------------------------
    @classmethod
    def open(cls, path: Path) -> GameruleStore:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise GameruleStorageError(
                f"could not open gamerule storage at {path}: {exc}"
            ) from exc
        return cls(conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            log.exception("closing gamerule storage failed")

    # -- per-world record ---------------------------------------
    def read_record(self, level_name: str) -> WorldRecord | None:
        try:
            row = self._conn.execute(
                "SELECT sampled_at, rules_json FROM gamerule_records WHERE level_name = ?",
                (level_name,),
            ).fetchone()
        except sqlite3.Error as exc:
            _fail(f"reading the record for {level_name!r}", exc)
        if row is None:
            return None
        return WorldRecord(level_name=level_name, sampled_at=row[0], values=json.loads(row[1]))

    def has_record(self, level_name: str) -> bool:
        try:
            return (
                self._conn.execute(
                    "SELECT 1 FROM gamerule_records WHERE level_name = ?", (level_name,)
                ).fetchone()
                is not None
            )
        except sqlite3.Error as exc:
            _fail(f"checking the record for {level_name!r}", exc)

    def write_record(
        self, level_name: str, values: dict[str, RuleValue], sampled_at: datetime | str
    ) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO gamerule_records (level_name, sampled_at, rules_json)
                VALUES (?, ?, ?)
                ON CONFLICT (level_name) DO UPDATE SET
                    sampled_at = excluded.sampled_at,
                    rules_json = excluded.rules_json
                """,
                (level_name, _iso(sampled_at), json.dumps(values)),
            )
        except sqlite3.Error as exc:
            _fail(f"writing the record for {level_name!r}", exc)

    # -- preferred defaults ------------------------------------
    def read_defaults(self) -> dict[str, RuleValue]:
        try:
            rows = self._conn.execute(
                "SELECT name, value_json FROM gamerule_defaults ORDER BY name"
            ).fetchall()
        except sqlite3.Error as exc:
            _fail("reading preferred defaults", exc)
        return {name: json.loads(value) for name, value in rows}

    def set_default(self, name: str, value: RuleValue) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO gamerule_defaults (name, value_json) VALUES (?, ?)
                ON CONFLICT (name) DO UPDATE SET value_json = excluded.value_json
                """,
                (name, json.dumps(value)),
            )
        except sqlite3.Error as exc:
            _fail(f"setting the default for {name!r}", exc)

    def clear_default(self, name: str) -> None:
        try:
            self._conn.execute("DELETE FROM gamerule_defaults WHERE name = ?", (name,))
        except sqlite3.Error as exc:
            _fail(f"clearing the default for {name!r}", exc)

    # -- restore marker (design.md D6) ------------------------
    def set_restore_marker(self, level_name: str, when: datetime | str) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO gamerule_restore_marker (id, level_name, set_at) VALUES (1, ?, ?)
                ON CONFLICT (id) DO UPDATE SET level_name = excluded.level_name,
                                              set_at = excluded.set_at
                """,
                (level_name, _iso(when)),
            )
        except sqlite3.Error as exc:
            _fail("setting the restore marker", exc)

    def restore_marker(self) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT level_name FROM gamerule_restore_marker WHERE id = 1"
            ).fetchone()
        except sqlite3.Error as exc:
            _fail("reading the restore marker", exc)
        return row[0] if row is not None else None

    def take_restore_marker(self, level_name: str) -> bool:
        """Consume the marker if it names ``level_name``. Returns whether it did.
        A marker for a different world is left in place."""
        try:
            cur = self._conn.execute(
                "DELETE FROM gamerule_restore_marker WHERE id = 1 AND level_name = ?",
                (level_name,),
            )
        except sqlite3.Error as exc:
            _fail("consuming the restore marker", exc)
        return cur.rowcount > 0

    def clear_restore_marker(self) -> None:
        try:
            self._conn.execute("DELETE FROM gamerule_restore_marker WHERE id = 1")
        except sqlite3.Error as exc:
            _fail("clearing the restore marker", exc)

    # -- unacknowledged report -------------------------------
    def read_report(self, level_name: str) -> Report | None:
        try:
            row = self._conn.execute(
                "SELECT kind, created_at, rules_json FROM gamerule_reports WHERE level_name = ?",
                (level_name,),
            ).fetchone()
        except sqlite3.Error as exc:
            _fail(f"reading the report for {level_name!r}", exc)
        if row is None:
            return None
        return Report(
            level_name=level_name, kind=row[0], created_at=row[1], rules=json.loads(row[2])
        )

    def write_report(self, report: Report) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO gamerule_reports (level_name, kind, created_at, rules_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (level_name) DO UPDATE SET
                    kind = excluded.kind,
                    created_at = excluded.created_at,
                    rules_json = excluded.rules_json
                """,
                (report.level_name, report.kind, report.created_at, json.dumps(report.rules)),
            )
        except sqlite3.Error as exc:
            _fail(f"writing the report for {report.level_name!r}", exc)

    def clear_report(self, level_name: str) -> None:
        try:
            self._conn.execute("DELETE FROM gamerule_reports WHERE level_name = ?", (level_name,))
        except sqlite3.Error as exc:
            _fail(f"clearing the report for {level_name!r}", exc)

    # -- pending stopped-server writes (task 5.5) ------------
    def read_pending(self, level_name: str) -> dict[str, RuleValue]:
        try:
            rows = self._conn.execute(
                "SELECT name, value_json FROM gamerule_pending WHERE level_name = ? ORDER BY name",
                (level_name,),
            ).fetchall()
        except sqlite3.Error as exc:
            _fail(f"reading pending writes for {level_name!r}", exc)
        return {name: json.loads(value) for name, value in rows}

    def set_pending(self, level_name: str, name: str, value: RuleValue) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO gamerule_pending (level_name, name, value_json) VALUES (?, ?, ?)
                ON CONFLICT (level_name, name) DO UPDATE SET value_json = excluded.value_json
                """,
                (level_name, name, json.dumps(value)),
            )
        except sqlite3.Error as exc:
            _fail(f"queuing a pending write for {level_name!r}", exc)

    def clear_pending(self, level_name: str) -> None:
        try:
            self._conn.execute(
                "DELETE FROM gamerule_pending WHERE level_name = ?", (level_name,)
            )
        except sqlite3.Error as exc:
            _fail(f"clearing pending writes for {level_name!r}", exc)


def open_store(path: Path) -> GameruleStore:
    """Open (creating if absent) the gamerule tables in the database at ``path``."""
    return GameruleStore.open(path)
