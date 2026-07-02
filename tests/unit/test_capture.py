"""Capture pipeline acceptance (PRD §6.7, §P0.2.2/3):
- no source ingested without consent;
- every observation carries provenance and is recallable.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from eidolon.capture import DocsMessagesConnector, ingest
from eidolon.capture.connector import ConsentGrant, connect
from eidolon.common.errors import ConsentMissing
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope


def _fetch():
    return [
        {"content": "worked on atlas migration today", "provenance": "docs.gdrive"},
        {"content": "posted standup update in #eng", "provenance": "chat.slack"},
    ]


def test_ingest_requires_matching_principal() -> None:
    grant = ConsentGrant(id="c1", principal_id="owner", source="docs")
    with pytest.raises(ConsentMissing):
        DocsMessagesConnector("someone-else", grant, _fetch, source="docs")


def test_ingest_refuses_uncovered_source() -> None:
    grant = ConsentGrant(id="c1", principal_id="p", source="docs")
    with pytest.raises(ConsentMissing):
        # grant covers "docs", not "messages"
        connect("messages", grant, _fetch)


def test_ingest_outside_window_refused() -> None:
    past = _dt.datetime(2020, 1, 1, tzinfo=_dt.UTC)
    grant = ConsentGrant(id="c1", principal_id="p", source="docs", not_after=past)
    with pytest.raises(ConsentMissing):
        connect("docs", grant, _fetch)


def test_ingested_traces_recallable_with_provenance() -> None:
    sage = InMemorySagePort()
    grant = ConsentGrant(
        id="c1", principal_id="p", source="docs",
        scope=Scope(selectors={"project": ["atlas"]}),
    )
    connector = connect("docs", grant, _fetch)
    mem_ids = ingest(sage, connector)
    assert len(mem_ids) == 2

    recalled = sage.recall("p", Scope(selectors={"project": ["atlas"]}), "atlas migration")
    assert recalled
    assert recalled[0].provenance in {"docs.gdrive", "chat.slack"}
    assert recalled[0].type == "observation"
