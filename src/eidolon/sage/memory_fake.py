"""In-memory :class:`SagePort` for the fast test/dev lane.

This is NOT a reimplementation of SAGE's consensus — it is a faithful *contract*
double that enforces exactly the guarantees other components rely on:

- **Principal isolation.** Storage is partitioned by ``principal_id``; a recall
  scoped to principal B can never observe principal A's memories.
- **Provenance.** Every write records its source tag; writes without one raise.
- **Content-hash / tamper-evidence.** Each record is hashed with the shared
  canonical hasher, mirroring SAGE's ``content_hash``. Attestations round-trip
  byte-identically through :meth:`replay`.

Production uses :class:`~eidolon.sage.client_adapter.SageClientAdapter` instead;
this double never sits in the production write path.
"""

from __future__ import annotations

import itertools
from collections import defaultdict

from eidolon.common.canonical import canonical_json, content_hash
from eidolon.common.errors import SageBackendError
from eidolon.sage.port import (
    Attestation,
    Memory,
    ReplayFilter,
    Scope,
    lexical_overlap,
    now_utc,
)


class InMemorySagePort:
    """Contract-faithful in-memory SAGE double."""

    def __init__(self) -> None:
        # principal_id -> list[Memory]
        self._memories: dict[str, list[Memory]] = defaultdict(list)
        # ledger_hash -> canonical attestation JSON (immutable once written)
        self._ledger: dict[str, str] = {}
        # preserve write order for deterministic replay
        self._ledger_order: list[str] = []
        self._ids = itertools.count(1)

    # -- writes -----------------------------------------------------------
    def observe(
        self,
        principal_id: str,
        content: str,
        type: str,
        provenance: str,
        scope: Scope | None = None,
    ) -> str:
        if not provenance:
            raise SageBackendError("observe requires a provenance tag")
        scope = scope or Scope()
        mem_id = f"mem-{next(self._ids)}"
        record = Memory(
            id=mem_id,
            principal_id=principal_id,
            content=content,
            type=type,
            provenance=provenance,
            scope=scope,
            content_hash=content_hash(
                {"principal_id": principal_id, "content": content, "type": type}
            ),
            author=principal_id,
            created_at=now_utc(),
        )
        self._memories[principal_id].append(record)
        return mem_id

    # -- reads ------------------------------------------------------------
    def recall(
        self, principal_id: str, scope: Scope, query: str, k: int = 10
    ) -> list[Memory]:
        # Principal isolation: only this principal's partition is ever consulted.
        candidates = self._memories.get(principal_id, [])
        wanted_domains = set(scope.domains())

        def in_scope(m: Memory) -> bool:
            if not wanted_domains:
                return True  # empty query scope = principal's whole partition
            mem_domains = set(m.scope.domains())
            if not mem_domains:
                return True  # general (unscoped) memory surfaces in any scope
            return bool(wanted_domains & mem_domains)

        scoped = [m for m in candidates if in_scope(m)]
        ranked = sorted(scoped, key=lambda m: lexical_overlap(query, m.content), reverse=True)
        return [m.model_copy(deep=True) for m in ranked[:k]]

    # -- attestation ledger ----------------------------------------------
    def attest(self, record: Attestation) -> str:
        payload = canonical_json(record)
        ledger_hash = content_hash(record)
        if ledger_hash in self._ledger:
            # Idempotent: identical record yields identical hash. Distinct
            # records essentially never collide (SHA-256).
            return ledger_hash
        self._ledger[ledger_hash] = payload
        self._ledger_order.append(ledger_hash)
        return ledger_hash

    def replay(self, filter: ReplayFilter) -> list[Attestation]:
        out: list[Attestation] = []
        for h in self._ledger_order:
            rec = Attestation.model_validate_json(self._ledger[h])
            if filter.ledger_hash and h != filter.ledger_hash:
                continue
            if filter.principal_id and rec.principal_id != filter.principal_id:
                continue
            if filter.action_class and rec.action_class != filter.action_class:
                continue
            if filter.since and rec.timestamp < filter.since:
                continue
            out.append(rec)
            if len(out) >= filter.limit:
                break
        return out

    # -- test helpers -----------------------------------------------------
    def ledger_bytes(self, ledger_hash: str) -> str:
        """Raw stored canonical JSON for byte-identity assertions."""
        return self._ledger[ledger_hash]
