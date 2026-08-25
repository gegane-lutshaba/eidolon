"""Persistent storage for the Postgres :class:`SagePort` (single-box lane).

Two tables, defined on the shared :class:`eidolon.data.db.Base` so ``init_db``
creates them alongside the operational store:

- ``sage_memories`` — the principal-partitioned observation store. Recall reads
  a principal's partition and ranks in Python with the *same* lexical relevance
  as every other port, so recall (and therefore ETHOS fidelity grounding) is
  backend-identical.
- ``sage_ledger`` — the HORKOS attestation ledger as an append-only, **hash-
  chained** log. ``chain_hash[n] = H(chain_hash[n-1] ‖ ledger_hash[n])`` links
  each entry to its predecessor, so any retroactive edit, deletion, or reorder
  breaks the chain and is caught by :meth:`PostgresSagePort.verify_chain`. This
  is what carries SAGE's tamper-evidence guarantee onto a single VPS without a
  BFT consensus cluster.

Only the port implementation (``pg_port.py``) touches these rows; the SAGE seam
rule (PRD §6.1) still holds — nothing else imports them.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import JSON, BigInteger, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from eidolon.data.db import Base

# BIGSERIAL on Postgres; SQLite (test lane) only autoincrements INTEGER PKs.
_AutoKey = BigInteger().with_variant(Integer, "sqlite")


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class SageMemoryRow(Base):
    __tablename__ = "sage_memories"

    # Monotonic surrogate key = insertion order (drives deterministic recall).
    seq: Mapped[int] = mapped_column(_AutoKey, primary_key=True, autoincrement=True)
    # Set to "mem-{seq}" immediately after the seq is assigned (see observe()).
    mem_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String, default="memory")
    provenance: Mapped[str] = mapped_column(String)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)  # selector-type -> [values]
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    content_hash: Mapped[str] = mapped_column(String)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SageLedgerRow(Base):
    __tablename__ = "sage_ledger"

    # Monotonic surrogate key = append order (drives deterministic replay).
    seq: Mapped[int] = mapped_column(_AutoKey, primary_key=True, autoincrement=True)
    # H(record): the attestation's own content hash and the value returned to
    # callers. Unique -> attest() is idempotent for an identical record.
    ledger_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    action_class: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Tamper-evident chain: prev_chain is the predecessor's chain_hash ("" at
    # genesis); chain_hash = H(prev_chain ‖ ledger_hash).
    prev_chain: Mapped[str] = mapped_column(String, default="")
    chain_hash: Mapped[str] = mapped_column(String, index=True)
    # Canonical JSON of the Attestation — the authoritative, round-trippable copy.
    payload: Mapped[str] = mapped_column(Text)
