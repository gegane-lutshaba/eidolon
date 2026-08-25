"""Audit console: ledger integrity surfacing, hash-sealed evidence export, CSV,
and the HTTP endpoints that back the server-rendered console.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from eidolon.api import audit as audit_svc
from eidolon.common.canonical import content_hash
from eidolon.data.db import get_engine, init_db
from eidolon.sage import InMemorySagePort
from eidolon.sage.pg_port import PostgresSagePort
from eidolon.sage.port import Attestation, ReplayFilter, now_utc

FIXED = _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)


def _att(principal: str, action: str, action_class: str, **kw) -> Attestation:
    return Attestation(
        action=action,
        action_class=action_class,
        timestamp=kw.pop("ts", now_utc()),
        principal_id=principal,
        **kw,
    )


# --- chain status surfacing --------------------------------------------
def test_chain_status_unsupported_for_memory_backend() -> None:
    st = audit_svc.chain_status(InMemorySagePort())
    assert st["supported"] is False
    assert st["backend"] == "InMemorySagePort"


def test_chain_status_reports_postgres_chain(tmp_path) -> None:
    url = f"sqlite:///{tmp_path/'a.db'}"
    init_db(url)
    pg = PostgresSagePort(session_factory=sessionmaker(bind=get_engine(url), future=True))
    pg.attest(_att("alice", "post", "status-update"))
    st = audit_svc.chain_status(pg)
    assert st == {"supported": True, "ok": True, "length": 1, "broken_at": None}


# --- evidence bundle ----------------------------------------------------
def test_evidence_bundle_is_hash_sealed() -> None:
    sage = InMemorySagePort()
    sage.attest(_att("alice", "post", "status-update", autonomy_level="AUTONOMOUS_ACT"))
    sage.attest(_att("alice", "wire", "payment", autonomy_level="DENY", would_have_escalated=True))

    bundle = audit_svc.evidence_bundle(
        sage, ReplayFilter(principal_id="alice"), generated_at=FIXED
    )
    assert bundle["kind"] == "eidolon.evidence-bundle.v1"
    assert bundle["count"] == 2
    assert bundle["chain"]["supported"] is False
    # every row carries a cross-referenceable ledger hash
    assert all("ledger_hash" in r for r in bundle["attestations"])

    # bundle_hash seals the whole payload: recompute over the rest.
    sealed = dict(bundle)
    h = sealed.pop("bundle_hash")
    assert content_hash(sealed) == h


def test_evidence_bundle_filters_by_principal() -> None:
    sage = InMemorySagePort()
    sage.attest(_att("alice", "a", "status-update"))
    sage.attest(_att("bob", "b", "status-update"))
    bundle = audit_svc.evidence_bundle(sage, ReplayFilter(principal_id="alice"))
    assert bundle["count"] == 1
    assert bundle["attestations"][0]["principal_id"] == "alice"


# --- csv ----------------------------------------------------------------
def test_ledger_csv_has_header_and_rows() -> None:
    sage = InMemorySagePort()
    sage.attest(_att("alice", "post", "status-update", autonomy_level="AUTONOMOUS_ACT", result="acted"))
    sage.attest(_att("alice", "wire", "payment", autonomy_level="DENY", result="denied"))

    text = audit_svc.ledger_csv(sage, ReplayFilter(principal_id="alice"))
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    assert {r["action"] for r in rows} == {"post", "wire"}
    assert rows[0]["ledger_hash"]  # populated
    assert "autonomy_level" in rows[0]


# --- HTTP endpoints -----------------------------------------------------
@pytest.fixture
def client():
    from eidolon.api import app as app_module

    rt = app_module.runtime()  # memory backend in the test lane
    rt.sage.attest(_att("alice", "post_status", "status-update", autonomy_level="AUTONOMOUS_ACT"))
    rt.sage.attest(_att("alice", "send_email", "draft-comm", autonomy_level="DRAFT"))
    return TestClient(app_module.app)


def test_console_page_served(client) -> None:
    r = client.get("/audit")
    assert r.status_code == 200
    assert "audit console" in r.text.lower()


def test_audit_chain_endpoint(client) -> None:
    r = client.get("/audit/chain")
    assert r.status_code == 200
    assert r.json()["supported"] is False  # memory backend


def test_export_json_is_attachment_bundle(client) -> None:
    r = client.get("/audit/export.json", params={"principal_id": "alice"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert body["kind"] == "eidolon.evidence-bundle.v1"
    assert body["count"] >= 2
    assert "bundle_hash" in body


def test_export_csv_is_attachment(client) -> None:
    r = client.get("/audit/export.csv", params={"principal_id": "alice"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.splitlines()[0].startswith("timestamp,principal_id,action")
