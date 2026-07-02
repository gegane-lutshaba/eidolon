"""Multi-connector capture acceptance (PRD §6.7, §12 — v2):
- multiple source connectors, each consent-gated and provenance-tagged;
- built-in normalizers for calendar/email/code shape records into traces;
- ingest_all captures all sources; each still requires its own consent;
- new sources can be registered (extensibility for new profiles).
"""

from __future__ import annotations

import pytest

from eidolon.capture import (
    ConsentGrant,
    SourceSpec,
    connect,
    ingest,
    ingest_all,
    known_sources,
    register_source,
)
from eidolon.common.errors import ConsentMissing
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope


def _grant(source: str, principal="p") -> ConsentGrant:
    return ConsentGrant(id=f"c-{source}", principal_id=principal, source=source,
                        scope=Scope(selectors={"project": ["atlas"]}))


def test_builtin_sources_available() -> None:
    for s in ("documents", "messages", "calendar", "email", "code"):
        assert s in known_sources()


def test_calendar_normalizer() -> None:
    conn = connect("calendar", _grant("calendar"),
                   lambda: [{"title": "Atlas standup", "start": "2026-07-03T09:00", "notes": "launch prep"}])
    traces = conn.traces()
    assert traces[0].provenance == "calendar.mcp"
    assert "Atlas standup" in traces[0].content and "launch prep" in traces[0].content


def test_email_and_code_normalizers() -> None:
    email = connect("email", _grant("email"),
                    lambda: [{"subject": "Re: atlas", "body": "on track for friday"}]).traces()
    assert email[0].provenance == "email.mcp"
    assert "Re: atlas" in email[0].content and "on track" in email[0].content

    code = connect("code", _grant("code"),
                   lambda: [{"sha": "abcdef1234567890", "message": "fix atlas migration"}]).traces()
    assert code[0].provenance == "code.mcp"
    assert "commit abcdef1234" in code[0].content and "fix atlas migration" in code[0].content


def test_ingest_all_multi_source_with_provenance() -> None:
    sage = InMemorySagePort()
    connectors = [
        connect("documents", _grant("documents"), lambda: [{"content": "atlas design doc"}]),
        connect("calendar", _grant("calendar"), lambda: [{"title": "atlas review", "start": "2026-07-03"}]),
        connect("email", _grant("email"), lambda: [{"subject": "atlas", "body": "status ok"}]),
    ]
    result = ingest_all(sage, connectors)
    assert set(result) == {"documents", "calendar", "email"}
    assert all(len(ids) == 1 for ids in result.values())

    recalled = sage.recall("p", Scope(selectors={"project": ["atlas"]}), "atlas", k=20)
    provenances = {m.provenance for m in recalled}
    assert {"documents.mcp", "calendar.mcp", "email.mcp"}.issubset(provenances)


def test_each_source_requires_its_own_consent() -> None:
    # A calendar grant cannot authorize email capture.
    cal_grant = _grant("calendar")
    with pytest.raises(ConsentMissing):
        connect("email", cal_grant, lambda: [{"subject": "x", "body": "y"}])


def test_register_new_source() -> None:
    register_source(SourceSpec(
        source="tickets", default_provenance="tickets.mcp",
        normalize=lambda rec: (f"[{rec['key']}] {rec['summary']}", "jira.mcp"),
    ))
    assert "tickets" in known_sources()
    sage = InMemorySagePort()
    conn = connect("tickets", _grant("tickets"), lambda: [{"key": "ATL-1", "summary": "atlas bug"}])
    ids = ingest(sage, conn)
    assert len(ids) == 1
    recalled = sage.recall("p", Scope(selectors={"project": ["atlas"]}), "atlas", k=5)
    assert recalled[0].provenance == "jira.mcp"
    assert "ATL-1" in recalled[0].content
