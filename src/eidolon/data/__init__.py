"""Operational store (Postgres + pgvector) — PRD §7, §11.

Holds principal-owned operational records: Principal (tenant), Twin,
DomainProfile registry, Delegation store, ConsentGrant, ContinuityGrant.
Attestations and memories live on the SAGE ledger (not here) — this store keeps
only a forensic reference to their ledger hashes.
"""

from eidolon.data.db import Base, get_engine, get_sessionmaker, init_db
from eidolon.data.models import (
    ConsentGrantRow,
    ContinuityGrantRow,
    DelegationRow,
    DomainProfileRow,
    PrincipalRow,
    TwinRow,
)

__all__ = [
    "Base",
    "get_engine",
    "get_sessionmaker",
    "init_db",
    "PrincipalRow",
    "TwinRow",
    "DomainProfileRow",
    "DelegationRow",
    "ConsentGrantRow",
    "ContinuityGrantRow",
]
