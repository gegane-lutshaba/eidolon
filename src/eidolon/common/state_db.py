"""A small durable state file (stdlib ``sqlite3``) for single-box deployments.

Holds what must survive restarts and be visible across processes when there is
no Postgres: revocations, dead-man heartbeats, and budget consumption. WAL mode
lets one process see another's revocation on its very next check. No ORM, so it
works in the core install.
"""

from __future__ import annotations

import pathlib
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS revocations (delegation_id TEXT PRIMARY KEY, revoked_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS heartbeats (principal_id TEXT PRIMARY KEY, last_beat TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS budget_events (
    principal_id TEXT NOT NULL, dim TEXT NOT NULL, ts TEXT NOT NULL, amount INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS budget_events_key ON budget_events (principal_id, dim, ts);
"""


class StateDB:
    def __init__(self, path: str | pathlib.Path) -> None:
        self.path = pathlib.Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None,
                                     check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(_SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
