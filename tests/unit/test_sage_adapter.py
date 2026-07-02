"""P0.1 acceptance (PRD §6.1):
- A memory written under principal A is never returned by recall scoped to B.
- Every write carries provenance and is retrievable.
- An attestation write returns a ledger hash that replay retrieves byte-identically.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from eidolon.common.canonical import canonical_json
from eidolon.common.errors import SageBackendError
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Attestation, ReplayFilter, Scope


@pytest.fixture
def sage() -> InMemorySagePort:
    return InMemorySagePort()


def test_cross_principal_isolation(sage: InMemorySagePort) -> None:
    sage.observe("principal-A", "secret roadmap for atlas", "memory", "docs.read")
    sage.observe("principal-B", "unrelated content", "memory", "docs.read")

    a_recall = sage.recall("principal-A", Scope(), "roadmap", k=10)
    b_recall = sage.recall("principal-B", Scope(), "roadmap", k=10)

    assert any("roadmap" in m.content for m in a_recall)
    assert all("roadmap" not in m.content for m in b_recall)
    # B cannot see A's memory under any query.
    assert all(m.principal_id == "principal-B" for m in b_recall)


def test_provenance_required(sage: InMemorySagePort) -> None:
    with pytest.raises(SageBackendError):
        sage.observe("principal-A", "content", "memory", "")


def test_provenance_recorded_and_retrievable(sage: InMemorySagePort) -> None:
    mem_id = sage.observe("principal-A", "atlas launch on friday", "memory", "chat.slack")
    assert mem_id
    recalled = sage.recall("principal-A", Scope(), "atlas launch", k=5)
    assert recalled and recalled[0].provenance == "chat.slack"
    assert recalled[0].content_hash is not None


def test_scope_filters_recall(sage: InMemorySagePort) -> None:
    sage.observe(
        "principal-A", "atlas note", "memory", "docs.read",
        scope=Scope(selectors={"project": ["atlas"]}),
    )
    sage.observe(
        "principal-A", "borealis note", "memory", "docs.read",
        scope=Scope(selectors={"project": ["borealis"]}),
    )
    atlas = sage.recall("principal-A", Scope(selectors={"project": ["atlas"]}), "note")
    assert [m.content for m in atlas] == ["atlas note"]


def test_attest_replay_byte_identical(sage: InMemorySagePort) -> None:
    record = Attestation(
        action="post status update",
        action_class="post-status",
        timestamp=_dt.datetime(2026, 7, 2, 12, 0, tzinfo=_dt.UTC),
        delegation_chain=["root-hash", "twin-hash"],
        evidence_refs=["mem-1", "mem-2"],
        ethos_version="v0-abc",
        judgment="PROCEED",
        confidence=0.91,
        autonomy_level="NOTIFY_ACT",
        result="ok",
        principal_id="principal-A",
    )
    ledger_hash = sage.attest(record)
    assert ledger_hash

    replayed = sage.replay(ReplayFilter(principal_id="principal-A"))
    assert len(replayed) == 1
    # Byte-identity: re-canonicalizing the replayed record reproduces the exact
    # bytes stored on the ledger.
    assert canonical_json(replayed[0]) == sage.ledger_bytes(ledger_hash)
    assert canonical_json(replayed[0]) == canonical_json(record)


def test_replay_filters(sage: InMemorySagePort) -> None:
    def mk(cls: str) -> Attestation:
        return Attestation(
            action=f"do {cls}",
            action_class=cls,
            timestamp=_dt.datetime(2026, 7, 2, 12, 0, tzinfo=_dt.UTC),
            principal_id="principal-A",
        )

    sage.attest(mk("answer-status"))
    sage.attest(mk("post-status"))
    only_post = sage.replay(ReplayFilter(principal_id="principal-A", action_class="post-status"))
    assert [r.action_class for r in only_post] == ["post-status"]


def test_attest_is_idempotent(sage: InMemorySagePort) -> None:
    record = Attestation(
        action="x", action_class="answer-status",
        timestamp=_dt.datetime(2026, 7, 2, tzinfo=_dt.UTC),
        principal_id="principal-A",
    )
    h1 = sage.attest(record)
    h2 = sage.attest(record)
    assert h1 == h2
    assert len(sage.replay(ReplayFilter(principal_id="principal-A"))) == 1
