"""Postgres-backed :class:`SagePort` — the single-VPS persistence lane.

This is the production path when you deploy EIDOLON on one box (``docker compose
up``) without a multi-node SAGE cluster. It is a faithful *contract* implementation
of :class:`~eidolon.sage.port.SagePort`, holding exactly the guarantees the rest
of the system relies on:

- **Principal isolation.** Rows are partitioned by ``principal_id``; a recall
  scoped to principal B never reads principal A's memories.
- **Recall parity.** Scope filtering and lexical ranking are the *same* logic as
  the in-memory port (:func:`~eidolon.sage.port.lexical_overlap`), so decisions
  and ETHOS grounding are backend-identical.
- **Tamper-evidence.** The attestation ledger is an append-only hash chain
  (:mod:`eidolon.sage.pg_store`); :meth:`verify_chain` detects any edit,
  deletion, or reorder — the property SAGE's consensus gives you for free, made
  to hold on a single host.
- **Byte-identical replay.** Attestations are stored as canonical JSON and
  round-trip through :meth:`replay` unchanged.

The full-strength substrate is still :class:`~eidolon.sage.client_adapter.SageClientAdapter`
(BFT consensus, distributed). Choose the backend with ``EIDOLON_SAGE_BACKEND``.
"""

from __future__ import annotations

import datetime as _dt
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from eidolon.common.canonical import canonical_json, content_hash
from eidolon.common.errors import SageBackendError
from eidolon.sage.pg_store import SageLedgerRow, SageMemoryRow
from eidolon.sage.port import (
    Attestation,
    Memory,
    ReplayFilter,
    Scope,
    lexical_overlap,
    now_utc,
)

# Recall loads at most this many of a principal's most-recent memories before
# ranking in Python. A scale safety valve for very large single-box stores;
# far above any realistic beachhead volume, so recall stays parity-exact.
DEFAULT_RECALL_PREFETCH = 5000


def _as_utc(dt: _dt.datetime | None) -> _dt.datetime | None:
    """Normalise a possibly-naive stored timestamp to tz-aware UTC.

    Postgres round-trips tz-aware datetimes; SQLite (test lane) drops the tz.
    Normalising here keeps :class:`Memory` timestamps consistent across both.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_dt.UTC)


def _chain_link(prev_chain: str, ledger_hash: str) -> str:
    """chain_hash = H(prev_chain ‖ ledger_hash)."""
    return content_hash({"prev": prev_chain, "record": ledger_hash})


class ChainStatus(NamedTuple):
    """Result of :meth:`PostgresSagePort.verify_chain`."""

    ok: bool
    length: int
    broken_at: int | None = None  # seq of the first tampered/broken entry


class PostgresSagePort:
    """Contract-faithful, persistent SAGE port over SQLAlchemy/Postgres."""

    def __init__(
        self,
        session_factory: sessionmaker | None = None,
        *,
        recall_prefetch: int = DEFAULT_RECALL_PREFETCH,
    ) -> None:
        if session_factory is None:
            # Default wiring: ensure the schema exists and bind the shared engine.
            from eidolon.data.db import get_sessionmaker, init_db

            init_db()
            session_factory = get_sessionmaker()
        self._sf = session_factory
        self._recall_prefetch = recall_prefetch

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
        ch = content_hash({"principal_id": principal_id, "content": content, "type": type})
        with self._sf() as s:
            row = SageMemoryRow(
                principal_id=principal_id,
                content=content,
                type=type,
                provenance=provenance,
                scope=scope.selectors,
                content_hash=ch,
                author=principal_id,
                created_at=now_utc(),
            )
            s.add(row)
            s.flush()  # assign seq
            row.mem_id = f"mem-{row.seq}"
            s.commit()
            return row.mem_id

    # -- reads ------------------------------------------------------------
    def recall(self, principal_id: str, scope: Scope, query: str, k: int = 10) -> list[Memory]:
        wanted_domains = set(scope.domains())
        with self._sf() as s:
            # Newest N of this principal's partition (principal isolation) ...
            rows = (
                s.execute(
                    select(SageMemoryRow)
                    .where(SageMemoryRow.principal_id == principal_id)
                    .order_by(SageMemoryRow.seq.desc())
                    .limit(self._recall_prefetch)
                )
                .scalars()
                .all()
            )
        # ... restored to insertion order so ties break exactly like every port.
        mems = [self._to_memory(r) for r in reversed(rows)]

        def in_scope(m: Memory) -> bool:
            if not wanted_domains:
                return True  # empty query scope = principal's whole partition
            mem_domains = set(m.scope.domains())
            if not mem_domains:
                return True  # general (unscoped) memory surfaces in any scope
            return bool(wanted_domains & mem_domains)

        scoped = [m for m in mems if in_scope(m)]
        ranked = sorted(scoped, key=lambda m: lexical_overlap(query, m.content), reverse=True)
        return ranked[:k]

    # -- attestation ledger ----------------------------------------------
    def attest(self, record: Attestation) -> str:
        ledger_hash = content_hash(record)
        payload = canonical_json(record)
        with self._sf() as s:
            exists = s.execute(
                select(SageLedgerRow.seq).where(SageLedgerRow.ledger_hash == ledger_hash)
            ).first()
            if exists:
                return ledger_hash  # idempotent: identical record -> identical hash
            last = (
                s.execute(select(SageLedgerRow).order_by(SageLedgerRow.seq.desc()).limit(1))
                .scalars()
                .first()
            )
            prev_chain = last.chain_hash if last else ""
            s.add(
                SageLedgerRow(
                    ledger_hash=ledger_hash,
                    principal_id=record.principal_id,
                    action_class=record.action_class,
                    timestamp=record.timestamp,
                    prev_chain=prev_chain,
                    chain_hash=_chain_link(prev_chain, ledger_hash),
                    payload=payload,
                )
            )
            s.commit()
        return ledger_hash

    def replay(self, filter: ReplayFilter) -> list[Attestation]:
        stmt = select(SageLedgerRow).order_by(SageLedgerRow.seq.asc())
        if filter.ledger_hash:
            stmt = stmt.where(SageLedgerRow.ledger_hash == filter.ledger_hash)
        if filter.principal_id:
            stmt = stmt.where(SageLedgerRow.principal_id == filter.principal_id)
        if filter.action_class:
            stmt = stmt.where(SageLedgerRow.action_class == filter.action_class)
        with self._sf() as s:
            rows = s.execute(stmt).scalars().all()
        out: list[Attestation] = []
        for r in rows:
            rec = Attestation.model_validate_json(r.payload)
            # `since` is applied on the tz-aware payload timestamp so it is
            # backend-independent (SQLite would otherwise strip the tz).
            if filter.since and rec.timestamp < filter.since:
                continue
            out.append(rec)
            if len(out) >= filter.limit:
                break
        return out

    # -- tamper-evidence / helpers ---------------------------------------
    def verify_chain(self) -> ChainStatus:
        """Recompute the whole hash chain; detect any edit, deletion, or reorder.

        Returns the first ``seq`` at which the ledger diverges from a clean
        recomputation, or ``ok=True`` if the entire chain is intact.
        """
        with self._sf() as s:
            rows = s.execute(select(SageLedgerRow).order_by(SageLedgerRow.seq.asc())).scalars().all()
        prev_chain = ""
        for r in rows:
            # (a) payload integrity: the stored hash must match the payload.
            recomputed = content_hash(Attestation.model_validate_json(r.payload))
            if recomputed != r.ledger_hash:
                return ChainStatus(False, len(rows), r.seq)
            # (b) link integrity: predecessor + this entry must reproduce chain_hash.
            if r.prev_chain != prev_chain or r.chain_hash != _chain_link(prev_chain, r.ledger_hash):
                return ChainStatus(False, len(rows), r.seq)
            prev_chain = r.chain_hash
        return ChainStatus(True, len(rows), None)

    def ledger_bytes(self, ledger_hash: str) -> str:
        """Raw stored canonical JSON for byte-identity assertions (parity with the fake)."""
        with self._sf() as s:
            payload = s.execute(
                select(SageLedgerRow.payload).where(SageLedgerRow.ledger_hash == ledger_hash)
            ).scalar_one()
        return payload

    def _to_memory(self, r: SageMemoryRow) -> Memory:
        return Memory(
            id=r.mem_id,
            principal_id=r.principal_id,
            content=r.content,
            type=r.type,
            provenance=r.provenance,
            scope=Scope(selectors=r.scope or {}),
            confidence_score=r.confidence_score,
            content_hash=r.content_hash,
            author=r.author,
            created_at=_as_utc(r.created_at),
        )
