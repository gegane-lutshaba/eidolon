"""Capture connectors (PRD §6.7, multi-connector — v2).

    connect(source, consent_grant, fetch) -> Connector
    ingest(connector) / ingest_all(connectors)     (see ingest.py)

A connector is a consent-gated source of provenance-tagged :class:`Trace`s. v1
shipped one connector (documents + messages); v2 generalizes capture into a
registry of source connectors — documents, messages, calendar, email, code — and
lets new profiles register their own sources. Each source declares a
:class:`SourceSpec` that normalizes its raw records into traces; the generic
:class:`MCPSourceConnector` handles consent enforcement uniformly.

Every connector is bound to a principal-owned :class:`ConsentGrant`. A connector
whose grant does not cover its source (wrong source, or outside its window)
refuses to produce traces.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, Field

from eidolon.common.errors import ConsentMissing
from eidolon.sage.port import Scope


class ConsentGrant(BaseModel):
    """Principal-owned consent for capturing a source (PRD §7)."""

    id: str
    principal_id: str
    source: str  # e.g. "documents", "messages", "calendar", "email", "code"
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


# -- source specs (normalize a source's raw records into trace fields) ---
class SourceSpec(BaseModel):
    """Declarative description of a capture source.

    ``normalize`` turns one raw MCP record (a dict) into ``(content, provenance)``.
    Sources differ in record shape (a doc vs a calendar event vs a commit), so
    each provides its own normalizer; all share consent + provenance handling.
    """

    model_config = {"arbitrary_types_allowed": True}

    source: str
    default_provenance: str
    normalize: Callable[[dict], tuple[str, str]]


def _passthrough(default_prov: str) -> Callable[[dict], tuple[str, str]]:
    def _n(rec: dict) -> tuple[str, str]:
        return rec["content"], rec.get("provenance", default_prov)

    return _n


def _calendar(rec: dict) -> tuple[str, str]:
    if "content" in rec:
        return rec["content"], rec.get("provenance", "calendar.mcp")
    title = rec.get("title", "(untitled event)")
    when = rec.get("start", "")
    notes = rec.get("notes", "")
    body = f"{title}" + (f" @ {when}" if when else "") + (f" — {notes}" if notes else "")
    return body, rec.get("provenance", "calendar.mcp")


def _email(rec: dict) -> tuple[str, str]:
    if "content" in rec:
        return rec["content"], rec.get("provenance", "email.mcp")
    subject = rec.get("subject", "(no subject)")
    body = rec.get("body", "")
    return f"{subject}\n{body}".strip(), rec.get("provenance", "email.mcp")


def _code(rec: dict) -> tuple[str, str]:
    if "content" in rec:
        return rec["content"], rec.get("provenance", "code.mcp")
    sha = rec.get("sha", "")[:10]
    message = rec.get("message", "")
    return f"commit {sha}: {message}".strip(), rec.get("provenance", "code.mcp")


# Built-in sources. New profiles may register their own via register_source().
_REGISTRY: dict[str, SourceSpec] = {
    "documents": SourceSpec(source="documents", default_provenance="documents.mcp",
                            normalize=_passthrough("documents.mcp")),
    "messages": SourceSpec(source="messages", default_provenance="messages.mcp",
                           normalize=_passthrough("messages.mcp")),
    "calendar": SourceSpec(source="calendar", default_provenance="calendar.mcp",
                           normalize=_calendar),
    "email": SourceSpec(source="email", default_provenance="email.mcp", normalize=_email),
    "code": SourceSpec(source="code", default_provenance="code.mcp", normalize=_code),
    # Back-compat alias for the v1 "docs" source name.
    "docs": SourceSpec(source="docs", default_provenance="docs.mcp",
                       normalize=_passthrough("docs.mcp")),
}


def register_source(spec: SourceSpec) -> None:
    """Register a new capture source (extensibility for new profiles)."""
    _REGISTRY[spec.source] = spec


def known_sources() -> list[str]:
    return sorted(_REGISTRY)


def _spec_for(source: str) -> SourceSpec:
    # Unknown sources still work via a generic passthrough spec, so a profile
    # can bind any MCP source without pre-registration.
    return _REGISTRY.get(source) or SourceSpec(
        source=source, default_provenance=f"{source}.mcp",
        normalize=_passthrough(f"{source}.mcp"),
    )


class MCPSourceConnector:
    """Generic, consent-gated connector over an MCP-tool ``fetch`` boundary.

    ``fetch`` returns raw records (in production it wraps an MCP client call; in
    tests it is a simple provider). The source's :class:`SourceSpec` normalizes
    each record; consent is enforced identically for every source.
    """

    def __init__(
        self,
        principal_id: str,
        consent: ConsentGrant,
        fetch: Callable[[], list[dict]],
        *,
        source: str | None = None,
        spec: SourceSpec | None = None,
    ) -> None:
        source = source or consent.source
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
        self._spec = spec or _spec_for(source)

    def traces(self) -> list[Trace]:
        records = self._fetch() or []
        out: list[Trace] = []
        for rec in records:
            content, provenance = self._spec.normalize(rec)
            out.append(Trace(content=content, provenance=provenance, scope=self._consent.scope))
        return out


# Back-compat: the v1 name for the documents+messages connector.
DocsMessagesConnector = MCPSourceConnector


def connect(source: str, consent_grant: ConsentGrant, fetch) -> MCPSourceConnector:
    """Factory matching the §6.7 ``connect`` signature (any registered source)."""
    return MCPSourceConnector(
        consent_grant.principal_id, consent_grant, fetch, source=source
    )
