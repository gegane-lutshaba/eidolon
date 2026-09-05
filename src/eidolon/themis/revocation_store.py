"""Revocation + dead-man's-switch state (PRD §6.3, §8).

Two implementations of one contract: the in-memory store for the fast lane,
and :class:`PostgresRevocationStore` for single-box deployments — a restart
must never resurrect revoked authority, so revocations and heartbeats persist
in the operational store. A clock is injected so tests can prove <1s
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
