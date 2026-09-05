"""Durable platform state (postgres backend): revocations, heartbeats, and the
approval inbox survive a service restart — modeled here as a FRESH store/queue
instance over the same database. A restart must never resurrect revoked
authority or lose a pending approval.

Runs on SQLite (the stores are DB-agnostic SQLAlchemy).
"""

from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy.orm import sessionmaker

from eidolon.data.db import get_engine, init_db
from eidolon.escalation import PostgresEscalationQueue
from eidolon.escalation.types import EscalationStatus
from eidolon.kairos.types import Decision, DecisionLevel
from eidolon.themis.revocation_store import PostgresRevocationStore
from eidolon.types import Action, Context


@pytest.fixture
def sf(tmp_path):
    url = f"sqlite:///{tmp_path/'state.db'}"
    init_db(url)
    return sessionmaker(bind=get_engine(url), future=True)


# -- revocations ---------------------------------------------------------
def test_revocation_survives_restart(sf) -> None:
    PostgresRevocationStore(session_factory=sf).revoke("deleg-1")
    fresh = PostgresRevocationStore(session_factory=sf)  # "restart"
    assert fresh.is_revoked("deleg-1")
    assert not fresh.is_revoked("deleg-2")


def test_revoke_is_idempotent(sf) -> None:
    store = PostgresRevocationStore(session_factory=sf)
    store.revoke("deleg-1")
    store.revoke("deleg-1")  # no crash, still revoked
    assert store.is_revoked("deleg-1")


def test_heartbeat_ttl_survives_restart(sf) -> None:
    t0 = _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)
    now = {"t": t0}
    clock = lambda: now["t"]  # noqa: E731

    PostgresRevocationStore(heartbeat_ttl_seconds=60, clock=clock, session_factory=sf).heartbeat("alice")
    fresh = PostgresRevocationStore(heartbeat_ttl_seconds=60, clock=clock, session_factory=sf)
    assert not fresh.is_dead_mans_expired("alice")   # within TTL
    now["t"] = t0 + _dt.timedelta(seconds=120)
    assert fresh.is_dead_mans_expired("alice")       # expired after restart too
    assert not fresh.is_dead_mans_expired("bob")     # never beat -> alive


# -- approval inbox ------------------------------------------------------
def _esc(principal: str = "alice"):
    action = Action(id="act-1", action_class="commit-action", description="wire it")
    ctx = Context(principal_id=principal, situation="commit-action")
    decision = Decision(level=DecisionLevel.ESCALATE, rationale="needs approval", output="ok?")
    return decision, action, ctx


def test_pending_escalation_survives_restart(sf) -> None:
    q1 = PostgresEscalationQueue(session_factory=sf)
    req = q1.enqueue(*_esc(), exec_context={"chain": [{"x": 1}], "certificates": []})

    q2 = PostgresEscalationQueue(session_factory=sf)  # "restart"
    assert [r.id for r in q2.list_all_pending()] == [req.id]
    assert q2.get(req.id).action.description == "wire it"
    assert q2.exec_context_for(req.id) == {"chain": [{"x": 1}], "certificates": []}


def test_deny_persists_across_restart(sf) -> None:
    q1 = PostgresEscalationQueue(session_factory=sf)
    req = q1.enqueue(*_esc())
    q1.deny(req.id)

    q2 = PostgresEscalationQueue(session_factory=sf)
    assert q2.list_all_pending() == []
    assert q2.get(req.id).status == EscalationStatus.DENIED
    with pytest.raises(ValueError):
        q2.deny(req.id)  # already settled


def test_ids_continue_after_restart(sf) -> None:
    q1 = PostgresEscalationQueue(session_factory=sf)
    a = q1.enqueue(*_esc())
    q2 = PostgresEscalationQueue(session_factory=sf)
    b = q2.enqueue(*_esc())
    assert a.id != b.id


def test_expiry_persists(sf) -> None:
    q = PostgresEscalationQueue(default_ttl_seconds=0, session_factory=sf)
    req = q.enqueue(*_esc())
    q2 = PostgresEscalationQueue(session_factory=sf)
    assert q2.list_all_pending() == []  # expired on read
    assert q2.get(req.id).status == EscalationStatus.EXPIRED


# -- the full loop across a restart, over HTTP ---------------------------
def test_escalate_restart_approve_over_http(tmp_path, monkeypatch) -> None:
    """The killer scenario for persistence: an action escalates, the SERVICE
    RESTARTS, and the principal can still approve — chain + certificates
    included. With in-memory state this loop breaks; on postgres it holds.
    """
    from fastapi.testclient import TestClient

    from eidolon.common import crypto

    url = f"sqlite:///{tmp_path/'api.db'}"
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "postgres")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", url)
    monkeypatch.setenv("EIDOLON_STYLE_ENABLED", "false")
    from eidolon.config import get_settings
    from eidolon.data import db as db_mod

    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module

    def restart() -> TestClient:
        app_module._runtime = None
        app_module._escalations = None
        return TestClient(app_module.app)

    try:
        client = restart()
        principal = crypto.generate_keypair()
        pid = principal.public_key_hex
        root = client.post("/delegations/mint", json={
            "signing_key": principal.signing_key_hex,
            "params": {"principal_id": pid, "issued_to": crypto.generate_keypair().public_key_hex,
                       "scope": {"project": ["atlas"]},
                       "permitted_classes": ["commit-action"],
                       "escalation_required": ["commit-action"], "max_autonomy": "autonomous",
                       "blast_radius_budget": {"scope_expansion": 0}}}).json()
        certs = [{"action_class": "commit-action", "agreement": 1.0, "calibration": 1.0,
                  "sample_size": 10, "ceiling": "draft"}]
        r = client.post("/resolve", json={
            "action": {"id": "a", "action_class": "commit-action",
                       "description": "sign the atlas contract",
                       "scope": {"selectors": {"project": ["atlas"]}}},
            "context": {"principal_id": pid, "situation": "contract"},
            "chain": [root], "certificates": certs}).json()
        assert r["level"] == "ESCALATE"
        esc_id = r["escalation_id"]

        client = restart()  # ---- the service restarts ----

        pending = client.get("/escalations").json()
        assert any(p["id"] == esc_id for p in pending)  # inbox survived
        ok = client.post(f"/escalations/{esc_id}/approve",
                         json={"signing_key": principal.signing_key_hex})
        assert ok.status_code == 200, ok.text
        assert ok.json()["decision"]["level"] == "NOTIFY_ACT"  # chain+certs survived too
    finally:
        app_module._runtime = None
        app_module._escalations = None
        get_settings.cache_clear()
        db_mod.get_engine.cache_clear()
        db_mod.get_sessionmaker.cache_clear()
