"""The SAGE seam (PRD §6.1).

``SagePort`` is the load-bearing interface every other component depends on:

    recall(principal_id, scope, query, k) -> [Memory]      # scoped semantic recall
    observe(principal_id, content, type, provenance) -> mem_id
    attest(record) -> ledger_hash                           # consensus ledger write
    replay(filter) -> [Attestation]                         # forensic query

Scoping maps onto SAGE's Organization -> Department -> Domain -> Agent model in
``scoping.py``. Attestations are persisted as consensus-committed memories in a
dedicated ledger domain (SAGE exposes no separate attest API); the memory's
``content_hash`` is the tamper-evident ledger hash.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class Scope(BaseModel):
    """A recall/write scope, expressed with a profile's mandate selectors.

    ``selectors`` maps selector-type -> allowed values, e.g.
    ``{"project": ["atlas"], "channel": ["#eng"]}``. An empty scope means
    "all of the principal's own memories" (still principal-isolated).
    """

    selectors: dict[str, list[str]] = Field(default_factory=dict)

    def domains(self) -> list[str]:
        """Flatten selectors into SAGE domain tags (``type:value``)."""
        return [f"{stype}:{val}" for stype, vals in sorted(self.selectors.items()) for val in vals]


class Memory(BaseModel):
    """A recalled or written observation (mirror of SAGE's MemoryRecord)."""

    id: str
    principal_id: str
    content: str
    type: str = "memory"  # memory | task | reflection | observation | attestation
    provenance: str  # source tag, e.g. "docs.read", "chat", "eidolon.horkos"
    scope: Scope = Field(default_factory=Scope)
    confidence_score: float = 1.0
    content_hash: str | None = None
    author: str | None = None
    created_at: _dt.datetime | None = None


class Attestation(BaseModel):
    """HORKOS attestation record persisted on the SAGE ledger (PRD §6.5).

    Defined here (not in ``horkos``) to keep the port free of upward imports.
    HORKOS re-exports this type.
    """

    action: str
    action_class: str
    timestamp: _dt.datetime
    delegation_chain: list[str] = Field(default_factory=list)  # hashes to root
    evidence_refs: list[str] = Field(default_factory=list)  # mem_ids
    ethos_version: str | None = None
    judgment: str | None = None
    confidence: float | None = None
    autonomy_level: str | None = None
    result: str | None = None
    would_have_escalated: bool = False
    principal_id: str
    signature: str | None = None


class ReplayFilter(BaseModel):
    """Forensic query for :meth:`SagePort.replay`."""

    principal_id: str | None = None
    action_class: str | None = None
    ledger_hash: str | None = None
    since: _dt.datetime | None = None
    limit: int = 1000


@runtime_checkable
class SagePort(Protocol):
    """The single seam onto SAGE. Implementations must enforce principal
    isolation: a memory written under principal A is never returned by a recall
    scoped to principal B."""

    def recall(
        self, principal_id: str, scope: Scope, query: str, k: int = 10
    ) -> list[Memory]: ...

    def observe(
        self,
        principal_id: str,
        content: str,
        type: str,
        provenance: str,
        scope: Scope | None = None,
    ) -> str: ...

    def attest(self, record: Attestation) -> str: ...

    def replay(self, filter: ReplayFilter) -> list[Attestation]: ...


def now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def as_jsonable(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
