"""Revocation + dead-man's-switch state (PRD §6.3, §8).

One contract, three implementations: the in-memory store for the fast lane;
:class:`SqliteRevocationStore`, a state file for single-box deployments without
Postgres (shared by every process on the box); and
:class:`PostgresRevocationStore` over the operational store. A restart must
never resurrect revoked authority. A clock is injected so tests can prove <1s
revocation latency and dead-man auto-revocation deterministically.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable


def _default_clock() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class RevocationStore:
    def __init__(
        self,
        heartbeat_ttl_seconds: int = 3600,
        clock: Callable[[], _dt.datetime] = _default_clock,
    ) -> None:
        self._revoked: set[str] = set()
        self._heartbeats: dict[str, _dt.datetime] = {}
        self._ttl = _dt.timedelta(seconds=heartbeat_ttl_seconds)
        self._clock = clock

    # -- explicit revocation ---------------------------------------------
    def revoke(self, delegation_id: str) -> None:
        self._revoked.add(delegation_id)

    def is_revoked(self, delegation_id: str) -> bool:
        return delegation_id in self._revoked

    # -- dead-man's-switch ------------------------------------------------
    def heartbeat(self, principal_id: str) -> None:
        self._heartbeats[principal_id] = self._clock()

    def is_dead_mans_expired(self, principal_id: str) -> bool:
        """True iff the principal has missed the heartbeat window.

        A principal that has never sent a heartbeat is treated as alive until
        the first heartbeat establishes the timer, so freshly-minted roots work
        before any heartbeat. Once a heartbeat exists, absence past TTL trips.
        """
        last = self._heartbeats.get(principal_id)
        if last is None:
            return False
        return (self._clock() - last) > self._ttl


class PostgresRevocationStore(RevocationStore):
    """Durable revocations + heartbeats over the operational store.

    Same contract and injected clock as the in-memory store; a service restart
    never resurrects revoked authority or forgets a heartbeat timer.
    """

    def __init__(
        self,
        heartbeat_ttl_seconds: int = 3600,
        clock: Callable[[], _dt.datetime] = _default_clock,
        session_factory=None,
    ) -> None:
        super().__init__(heartbeat_ttl_seconds, clock)
        if session_factory is None:
            from eidolon.data.db import get_sessionmaker, init_db

            init_db()
            session_factory = get_sessionmaker()
        self._sf = session_factory

    # -- explicit revocation ---------------------------------------------
    def revoke(self, delegation_id: str) -> None:
        from eidolon.data.models import RevocationRow

        with self._sf() as s:
            if s.get(RevocationRow, delegation_id) is None:
                s.add(RevocationRow(delegation_id=delegation_id, revoked_at=self._clock()))
                s.commit()

    def is_revoked(self, delegation_id: str) -> bool:
        from eidolon.data.models import RevocationRow

        with self._sf() as s:
            return s.get(RevocationRow, delegation_id) is not None

    # -- dead-man's-switch ------------------------------------------------
    def heartbeat(self, principal_id: str) -> None:
        from eidolon.data.models import HeartbeatRow

        with self._sf() as s:
            row = s.get(HeartbeatRow, principal_id)
            if row is None:
                s.add(HeartbeatRow(principal_id=principal_id, last_beat=self._clock()))
            else:
                row.last_beat = self._clock()
            s.commit()

    def is_dead_mans_expired(self, principal_id: str) -> bool:
        from eidolon.data.models import HeartbeatRow

        with self._sf() as s:
            row = s.get(HeartbeatRow, principal_id)
        if row is None:
            return False
        last = row.last_beat if row.last_beat.tzinfo else row.last_beat.replace(tzinfo=_dt.UTC)
        return (self._clock() - last) > self._ttl


class SqliteRevocationStore(RevocationStore):
    """Durable revocations + heartbeats in a local state file (``StateDB``).

    Every process pointing at the same file sees a revocation on its next check,
    so revoking in the platform reaches an agent governed by another process.
    """

    def __init__(
        self,
        path_or_db,
        heartbeat_ttl_seconds: int = 3600,
        clock: Callable[[], _dt.datetime] = _default_clock,
    ) -> None:
        super().__init__(heartbeat_ttl_seconds, clock)
        from eidolon.common.state_db import StateDB

        self._db = path_or_db if isinstance(path_or_db, StateDB) else StateDB(path_or_db)

    def revoke(self, delegation_id: str) -> None:
        self._db.execute("INSERT OR IGNORE INTO revocations VALUES (?, ?)",
                         (delegation_id, self._clock().isoformat()))

    def is_revoked(self, delegation_id: str) -> bool:
        return bool(self._db.execute(
            "SELECT 1 FROM revocations WHERE delegation_id = ?", (delegation_id,)))

    def heartbeat(self, principal_id: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO heartbeats VALUES (?, ?)",
                         (principal_id, self._clock().isoformat()))

    def is_dead_mans_expired(self, principal_id: str) -> bool:
        rows = self._db.execute("SELECT last_beat FROM heartbeats WHERE principal_id = ?",
                                (principal_id,))
        if not rows:
            return False
        last = _dt.datetime.fromisoformat(rows[0][0])
        if last.tzinfo is None:
            last = last.replace(tzinfo=_dt.UTC)
        return (self._clock() - last) > self._ttl
