"""Revocation + dead-man's-switch state (PRD §6.3, §8).

An in-memory store (backed by Postgres in production via the data layer) that
records explicit revocations and per-principal heartbeats. A clock is injected
so tests can prove <1s revocation latency and dead-man auto-revocation
deterministically.
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
