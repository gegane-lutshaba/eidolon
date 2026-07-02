"""Capture connectors (PRD §6.7).

    connect(source, consent_grant) -> Connector
    ingest(connector) -> [mem_id]   (see ingest.py)

v1 ships one connector: documents + messages via MCP. The connector is a source
of provenance-tagged :class:`Trace` objects; ingestion writes them to SAGE.

Every connector is bound to a principal-owned :class:`ConsentGrant`. A connector
whose grant does not cover its source (or is outside its window) refuses to
produce traces.
"""

from __future__ import annotations

import datetime as _dt
from typing import Protocol

from pydantic import BaseModel, Field

from eidolon.common.errors import ConsentMissing
from eidolon.sage.port import Scope


class ConsentGrant(BaseModel):
    """Principal-owned consent for capturing a source (PRD §7)."""

    id: str
    principal_id: str
    source: str  # e.g. "docs", "messages"
    scope: Scope = Field(default_factory=Scope)
    not_before: _dt.datetime | None = None
    not_after: _dt.datetime | None = None

    def covers(self, source: str, at: _dt.datetime) -> bool:
        if self.source != source:
            return False
        if self.not_before and at < self.not_before:
            return False
        if self.not_after and at > self.not_after:
            return False
        return True


class Trace(BaseModel):
    """A single captured trace to be written as a SAGE observation."""

    content: str
    provenance: str  # source tag recorded on the observation
    scope: Scope = Field(default_factory=Scope)
    observed_at: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.UTC))


class Connector(Protocol):
    principal_id: str
    source: str

    def traces(self) -> list[Trace]: ...


class DocsMessagesConnector:
    """Documents + messages connector (MCP-backed).

    The ``fetch`` callable is the MCP tool boundary — in production it wraps an
    MCP client call (e.g. ``docs.read`` / ``chat.history``); in tests it is a
    simple provider of raw records. Either way, capture is gated by consent.
    """

    def __init__(
        self,
        principal_id: str,
        consent: ConsentGrant,
        fetch,  # () -> list[dict]  (raw records: {content, source, ...})
        *,
        source: str = "docs",
    ) -> None:
        if consent.principal_id != principal_id:
            raise ConsentMissing("consent grant is not owned by this principal")
        now = _dt.datetime.now(_dt.UTC)
        if not consent.covers(source, now):
            raise ConsentMissing(
                f"consent {consent.id} does not cover source {source!r} at {now.isoformat()}"
            )
        self.principal_id = principal_id
        self.source = source
        self._consent = consent
        self._fetch = fetch

    def traces(self) -> list[Trace]:
        records = self._fetch() or []
        out: list[Trace] = []
        for rec in records:
            out.append(
                Trace(
                    content=rec["content"],
                    provenance=rec.get("provenance", f"{self.source}.mcp"),
                    scope=self._consent.scope,
                )
            )
        return out


def connect(source: str, consent_grant: ConsentGrant, fetch) -> DocsMessagesConnector:
    """Factory matching the §6.7 ``connect`` signature."""
    return DocsMessagesConnector(
        consent_grant.principal_id, consent_grant, fetch, source=source
    )
