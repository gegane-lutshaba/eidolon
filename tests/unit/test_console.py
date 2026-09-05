"""Control-plane console: pages served + gated, and the operator approval inbox
(list-all-pending, approve/deny) behind admin auth.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.common import crypto
from eidolon.config import get_settings
from eidolon.escalation import EscalationQueue
from eidolon.kairos.types import Decision, DecisionLevel
from eidolon.types import Action, Context


@pytest.fixture
def tokens(monkeypatch):
    def _set(admin, auditor):
        for name, val in (("EIDOLON_ADMIN_TOKEN", admin), ("EIDOLON_AUDIT_TOKEN", auditor)):
            if val is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, val)
        get_settings.cache_clear()

    get_settings.cache_clear()
    yield _set
    get_settings.cache_clear()


@pytest.fixture
def client():
    from eidolon.api import app as app_module

    return TestClient(app_module.app)


# --- pages served + gated ----------------------------------------------
def test_delegations_page_served_open(client, tokens) -> None:
    tokens(None, None)  # dev-open
    r = client.get("/console/delegations")
    assert r.status_code == 200 and "Mint delegation" in r.text


def test_retired_console_routes_redirect(client, tokens) -> None:
    tokens(None, None)
    # the old console hub now points at mission control
    r = client.get("/console", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/live"


def test_delegations_is_admin_only(client, tokens) -> None:
    tokens("admin-t", "audit-t")
    r = client.get("/console/delegations", headers={"Authorization": "Bearer audit-t"})
    assert r.status_code == 403  # auditor may not reach the control plane
    assert client.get("/console/delegations",
                      headers={"Authorization": "Bearer admin-t"}).status_code == 200


# --- approval inbox -----------------------------------------------------
def _seed_pending(app_module, principal: str) -> str:
    q: EscalationQueue = app_module._escalations
    action = Action(id="act-1", action_class="wire-funds", description="pay invoice #42")
    ctx = Context(principal_id=principal, situation="wire-funds")
    decision = Decision(level=DecisionLevel.ESCALATE, rationale="needs approval", output="please approve")
    return q.enqueue(decision, action, ctx).id


def test_inbox_lists_all_pending(client, tokens) -> None:
    tokens(None, None)
    from eidolon.api import app as app_module

    app_module._escalations = EscalationQueue()  # isolate
    kp = crypto.generate_keypair()
    rid = _seed_pending(app_module, kp.public_key_hex)

    rows = client.get("/escalations").json()  # no principal_id -> full inbox
    assert any(r["id"] == rid for r in rows)


def test_deny_from_inbox(client, tokens) -> None:
    tokens(None, None)
    from eidolon.api import app as app_module

    app_module._escalations = EscalationQueue()
    kp = crypto.generate_keypair()
    rid = _seed_pending(app_module, kp.public_key_hex)

    assert client.post(f"/escalations/{rid}/deny").status_code == 200
    assert all(r["id"] != rid for r in client.get("/escalations").json())  # gone from pending


def test_inbox_requires_admin(client, tokens) -> None:
    tokens("admin-t", "audit-t")
    assert client.get("/escalations", headers={"Authorization": "Bearer audit-t"}).status_code == 403
    assert client.get("/escalations", headers={"Authorization": "Bearer admin-t"}).status_code == 200
