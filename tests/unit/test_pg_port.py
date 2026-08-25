"""Postgres :class:`SagePort` — contract parity with the in-memory port plus the
hash-chained tamper-evidence guarantee that lets a single VPS carry SAGE's
integrity property without a consensus cluster.

Runs on an on-disk SQLite database (no Postgres needed for the fast lane); the
port is DB-agnostic SQLAlchemy, so parity here implies parity on Postgres.
"""

from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy.orm import sessionmaker

from eidolon.common.canonical import canonical_json
from eidolon.common.errors import SageBackendError
from eidolon.data.db import get_engine, init_db
from eidolon.sage import InMemorySagePort
from eidolon.sage.pg_port import PostgresSagePort
from eidolon.sage.pg_store import SageLedgerRow
from eidolon.sage.port import Attestation, ReplayFilter, SagePort, Scope, now_utc


@pytest.fixture
def pg(tmp_path) -> PostgresSagePort:
    url = f"sqlite:///{tmp_path/'eidolon.db'}"
    init_db(url)
    return PostgresSagePort(session_factory=sessionmaker(bind=get_engine(url), future=True))


def _att(principal: str, action: str, action_class: str, ts=None) -> Attestation:
    return Attestation(
        action=action,
        action_class=action_class,
        timestamp=ts or now_utc(),
        principal_id=principal,
        result="ok",
    )


# --- structural contract ------------------------------------------------
def test_satisfies_port_protocol(pg) -> None:
    assert isinstance(pg, SagePort)


def test_provenance_is_required(pg) -> None:
    with pytest.raises(SageBackendError):
        pg.observe("alice", "some content", "memory", "")


# --- recall parity with the in-memory port ------------------------------
def test_recall_ranking_matches_fake(pg) -> None:
    fake = InMemorySagePort()
    docs = [
        "the quarterly revenue report is due friday",
        "revenue grew across every region this quarter",
        "lunch options near the office",
        "friday standup notes revenue targets",
    ]
    for d in docs:
        pg.observe("alice", d, "memory", "docs.read")
        fake.observe("alice", d, "memory", "docs.read")

    q = "revenue friday"
    got = [m.content for m in pg.recall("alice", Scope(), q, k=3)]
    want = [m.content for m in fake.recall("alice", Scope(), q, k=3)]
    assert got == want  # identical ranking incl. tie-breaking (insertion order)


def test_principal_isolation(pg) -> None:
    pg.observe("alice", "alice private strategy memo", "memory", "docs.read")
    pg.observe("bob", "bob unrelated note", "memory", "docs.read")
    got = pg.recall("bob", Scope(), "strategy memo", k=10)
    assert all(m.principal_id == "bob" for m in got)
    assert all("alice" not in m.content for m in got)


def test_scope_filtering(pg) -> None:
    pg.observe("alice", "atlas project kickoff", "memory", "docs", Scope(selectors={"project": ["atlas"]}))
    pg.observe("alice", "titan project kickoff", "memory", "docs", Scope(selectors={"project": ["titan"]}))
    pg.observe("alice", "general reminder kickoff", "memory", "docs")  # unscoped

    atlas = [m.content for m in pg.recall("alice", Scope(selectors={"project": ["atlas"]}), "kickoff", k=10)]
    assert "atlas project kickoff" in atlas
    assert "titan project kickoff" not in atlas  # out-of-scope excluded
    assert "general reminder kickoff" in atlas  # unscoped surfaces in any scope


# --- attestation ledger -------------------------------------------------
def test_attest_is_idempotent(pg) -> None:
    rec = _att("alice", "post_status", "status-update")
    h1 = pg.attest(rec)
    h2 = pg.attest(rec)
    assert h1 == h2
    assert len(pg.replay(ReplayFilter())) == 1  # only one row written


def test_replay_roundtrips_byte_identically(pg) -> None:
    rec = _att("alice", "send_note", "draft-comm")
    h = pg.attest(rec)
    assert pg.ledger_bytes(h) == canonical_json(rec)
    (back,) = pg.replay(ReplayFilter(ledger_hash=h))
    assert back == rec


def test_replay_filters(pg) -> None:
    old = now_utc() - _dt.timedelta(days=2)
    pg.attest(_att("alice", "a1", "status-update", ts=old))
    pg.attest(_att("alice", "a2", "draft-comm"))
    pg.attest(_att("bob", "b1", "status-update"))

    assert len(pg.replay(ReplayFilter())) == 3
    assert len(pg.replay(ReplayFilter(principal_id="alice"))) == 2
    assert len(pg.replay(ReplayFilter(action_class="status-update"))) == 2
    assert len(pg.replay(ReplayFilter(since=now_utc() - _dt.timedelta(hours=1)))) == 2
    assert len(pg.replay(ReplayFilter(limit=1))) == 1


def test_replay_preserves_append_order(pg) -> None:
    for i in range(5):
        pg.attest(_att("alice", f"a{i}", "status-update"))
    actions = [a.action for a in pg.replay(ReplayFilter())]
    assert actions == ["a0", "a1", "a2", "a3", "a4"]


# --- tamper-evidence (the single-box integrity guarantee) ---------------
def test_intact_chain_verifies(pg) -> None:
    for i in range(4):
        pg.attest(_att("alice", f"a{i}", "status-update"))
    status = pg.verify_chain()
    assert status.ok is True
    assert status.length == 4
    assert status.broken_at is None


def test_edited_payload_is_detected(pg) -> None:
    for i in range(4):
        pg.attest(_att("alice", f"a{i}", "status-update"))
    # Forge history: rewrite a committed attestation's payload in place.
    sf = pg._sf
    with sf() as s:
        row = s.query(SageLedgerRow).order_by(SageLedgerRow.seq.asc()).all()[1]
        tampered = _att("alice", "a1-FORGED", "status-update")
        row.payload = canonical_json(tampered)
        target_seq = row.seq
        s.commit()

    status = pg.verify_chain()
    assert status.ok is False
    assert status.broken_at == target_seq


def test_deleted_entry_is_detected(pg) -> None:
    for i in range(4):
        pg.attest(_att("alice", f"a{i}", "status-update"))
    sf = pg._sf
    with sf() as s:
        # Excise a middle entry — the successor's prev_chain no longer matches.
        victim = s.query(SageLedgerRow).order_by(SageLedgerRow.seq.asc()).all()[1]
        successor_seq = s.query(SageLedgerRow).order_by(SageLedgerRow.seq.asc()).all()[2].seq
        s.delete(victim)
        s.commit()

    status = pg.verify_chain()
    assert status.ok is False
    assert status.broken_at == successor_seq
