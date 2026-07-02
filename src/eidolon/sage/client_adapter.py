"""Live SAGE binding (PRD §6.1, §11).

Binds :class:`SagePort` to the real ``sage_sdk.SageClient`` talking to a
Dockerized node. The SDK surface was verified against a live node
(``sage-agent-sdk`` 10.9.1): writes go through ``propose(content, memory_type,
domain_tag, confidence, embedding, tags)``, recall through ``hybrid(query,
embedding, domain_tag, top_k)``, and forensic listing through
``list_memories(domain, ...)``. All memory writes pass through BFT consensus.

Isolation model (verified live): each principal writes into its own
principal-derived domain, so a recall scoped to principal B only ever queries
B's domain and can never observe principal A's memories. Attestations are
consensus-committed memories in a per-principal ledger domain; their canonical
JSON round-trips byte-identically, and the record's content hash is the ledger
hash.

Only this file changes if the SDK shape shifts; the port isolates the rest.
"""

from __future__ import annotations

import os
from typing import Any

from eidolon.common.canonical import canonical_json, content_hash
from eidolon.common.errors import SageBackendError
from eidolon.config import Settings
from eidolon.sage.port import Attestation, Memory, ReplayFilter, Scope, now_utc
from eidolon.sage.scoping import (
    attestation_domain,
    clamp_clearance,
    principal_domain,
    scope_tags,
)

_DEFAULT_CONFIDENCE = 0.8


class SageClientAdapter:
    """Adapter over the live ``sage_sdk.SageClient``."""

    def __init__(self, client: Any, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self._registered = False
        self._ensure_agent()

    @classmethod
    def from_settings(cls, settings: Settings) -> SageClientAdapter:
        try:
            from sage_sdk import AgentIdentity, SageClient
        except ImportError as exc:  # pragma: no cover
            raise SageBackendError(
                "sage_sdk not installed. `uv sync --extra sage` and `make up`."
            ) from exc

        key_path = os.path.expanduser(settings.sage_agent_key_path)
        if os.path.exists(key_path):
            identity = AgentIdentity.from_file(key_path)
        else:
            identity = AgentIdentity.generate()

        client = SageClient(
            base_url=settings.sage_base_url,
            identity=identity,
            ca_cert=settings.sage_ca_cert,
        )
        return cls(client, settings)

    # -- setup ------------------------------------------------------------
    def _ensure_agent(self) -> None:
        if self._registered:
            return
        try:
            self._client.register_agent(name="eidolon", role="member", provider="eidolon")
        except Exception:
            # Already registered (or personal mode): non-fatal.
            pass
        self._registered = True

    def _embed(self, text: str) -> list[float] | None:
        try:
            return self._client.embed(text)
        except Exception:
            return None  # let the server compute the embedding

    # -- SagePort ---------------------------------------------------------
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
        domain = principal_domain(principal_id)
        # SAGE's MemoryType enum is fixed (observation/task/fact/inference), so
        # EIDOLON's logical type (e.g. "skill", "observation") rides on a
        # ``kind:`` tag and is reconstructed on recall.
        tags = [*scope_tags(scope, provenance), f"kind:{type}"]
        resp = self._client.propose(
            content=content,
            memory_type="observation",
            domain_tag=domain,
            confidence=_DEFAULT_CONFIDENCE,
            embedding=self._embed(content),
            tags=tags,
            classification=clamp_clearance(1),
        )
        mem_id = getattr(resp, "memory_id", None) or getattr(resp, "id", None)
        if not mem_id:
            raise SageBackendError("SAGE propose returned no memory id")
        return str(mem_id)

    def recall(
        self, principal_id: str, scope: Scope, query: str, k: int = 10
    ) -> list[Memory]:
        domain = principal_domain(principal_id)
        emb = self._embed(query)
        try:
            resp = self._client.hybrid(
                query=query, embedding=emb, domain_tag=domain, top_k=k
            )
        except Exception as exc:
            raise SageBackendError(f"recall failed: {exc}") from exc
        wanted = set(scope.domains())
        out: list[Memory] = []
        for raw in _results(resp):
            mem = self._to_memory(raw, principal_id, scope)
            # Intra-principal scope narrowing (best-effort; cross-principal
            # isolation is already guaranteed by the per-principal domain).
            if wanted:
                have = set(_tags(raw))
                if not (wanted & have) and have:
                    continue
            out.append(mem)
        return out

    def attest(self, record: Attestation) -> str:
        domain = attestation_domain(record.principal_id, self._settings.sage_attestation_domain)
        payload = canonical_json(record)
        self._client.propose(
            content=payload,
            memory_type="observation",
            domain_tag=domain,
            confidence=_DEFAULT_CONFIDENCE,
            embedding=self._embed(f"{record.action_class} {record.action}"),
            tags=["attestation", record.action_class],
            classification=clamp_clearance(1),
        )
        # Deterministic ledger hash from the canonical record; replay re-parses
        # the stored canonical JSON and reproduces it byte-identically.
        return content_hash(record)

    def replay(self, filter: ReplayFilter) -> list[Attestation]:
        if filter.principal_id is None:
            raise SageBackendError("replay against live SAGE requires principal_id")
        domain = attestation_domain(filter.principal_id, self._settings.sage_attestation_domain)
        try:
            resp = self._client.list_memories(domain=domain, limit=filter.limit)
        except Exception as exc:
            raise SageBackendError(f"replay failed: {exc}") from exc
        records: list[Attestation] = []
        for raw in _results(resp):
            content = getattr(raw, "content", None)
            if not content:
                continue
            try:
                rec = Attestation.model_validate_json(content)
            except Exception:
                continue  # not an attestation record
            if filter.action_class and rec.action_class != filter.action_class:
                continue
            if filter.since and rec.timestamp < filter.since:
                continue
            records.append(rec)
        return records

    # -- mapping ----------------------------------------------------------
    def _to_memory(self, raw: Any, principal_id: str, scope: Scope) -> Memory:
        tags = _tags(raw)
        provenance = _provenance_from_tags(tags) or getattr(raw, "provider", None) or "sage"
        logical_type = _kind_from_tags(tags) or str(
            getattr(raw, "memory_type", "observation") or "observation"
        )
        return Memory(
            id=str(getattr(raw, "memory_id", None) or getattr(raw, "id", "") or ""),
            principal_id=principal_id,
            content=getattr(raw, "content", "") or "",
            type=logical_type,
            provenance=provenance,
            scope=scope,
            confidence_score=float(getattr(raw, "confidence_score", 1.0) or 1.0),
            content_hash=getattr(raw, "content_hash", None),
            author=getattr(raw, "provider", None),
            created_at=getattr(raw, "created_at", None) or now_utc(),
        )


# -- response helpers ----------------------------------------------------
def _results(resp: Any) -> list[Any]:
    if resp is None:
        return []
    for key in ("results", "memories", "items", "data"):
        val = getattr(resp, key, None)
        if val is not None:
            return list(val)
    if isinstance(resp, (list, tuple)):
        return list(resp)
    return [resp]


def _tags(raw: Any) -> list[str]:
    tags = getattr(raw, "tags", None)
    return list(tags) if tags else []


def _provenance_from_tags(tags: list[str]) -> str | None:
    for t in tags:
        if t.startswith("provenance:"):
            return t.split(":", 1)[1]
    return None


def _kind_from_tags(tags: list[str]) -> str | None:
    for t in tags:
        if t.startswith("kind:"):
            return t.split(":", 1)[1]
    return None
