"""Org governance dashboard: /api/governance/summary turns the attested ledger
into a readable posture (in-scope vs held vs denied, exfil blocked) — org-scoped.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'gov.db'}")
    monkeypatch.setenv("EIDOLON_ADMIN_TOKEN", "admin-t")
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module
    from eidolon.api import accounts as acc

    app_module._runtime = None
    app_module._live_sf = None
    app_module._login_hits.clear()
    client = TestClient(app_module.app)
    sf = app_module._live_store()
    yield client, sf, acc, app_module

    app_module._runtime = None
    app_module._live_sf = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def _signed_in_agent(client, sf, acc, email="dev@x.com"):
    user = acc.create_user(sf, email, "password12")
    org = acc.ensure_personal_org(sf, user["id"], user["email"])
    token = acc.open_session(sf, user["id"])
    client.cookies.set("eidolon_user", token)
    agent = acc.create_agent(sf, org, user["id"], "claude-code", "coding/operative")
    return agent["id"]


def _emit(sf, gid, level, allowed, cls="read-code", rationale=""):
    from eidolon.api import live

    live.record_event(sf, live.GatewayEvent(
        gateway_id=gid, agent="claude-code", tool="Read", action_class=cls,
        level=level, allowed=allowed, attestation_hash="h", rationale=rationale))


def test_governance_summary_counts(ctx) -> None:
    client, sf, acc, _ = ctx
    gid = _signed_in_agent(client, sf, acc)
    _emit(sf, gid, "NOTIFY_ACT", True)
    _emit(sf, gid, "AUTONOMOUS_ACT", True, "edit-code")
    _emit(sf, gid, "NOTIFY_ACT", True, "run-command")
    _emit(sf, gid, "ESCALATE", False, "destructive-command")
    _emit(sf, gid, "DENY", False, "destructive-command", "authority denied: destructive")
    _emit(sf, gid, "DENY", False, "web-egress",
          "authority denied: action touches excluded boundary ['data-exfiltration']")

    body = client.get("/api/governance/summary?days=30").json()
    assert body["actions_governed"] == 6
    assert body["allowed"] == 3
    assert body["held"] == 1
    assert body["denied"] == 2
    assert body["exfil_blocked"] == 1
    # per-class: destructive had 1 held + 1 denied -> blocked counts only the deny
    assert body["by_action_class"]["destructive-command"] == {"total": 2, "blocked": 1}
    assert body["by_action_class"]["web-egress"] == {"total": 1, "blocked": 1}
    assert body["agents_active"] == 1
    assert body["top_blocked"][0]["gateway_id"] == gid


def test_governance_summary_is_org_scoped(ctx) -> None:
    client, sf, acc, _ = ctx
    mine = _signed_in_agent(client, sf, acc, "me@x.com")
    # a different org's agent with its own events must NOT leak in
    other_user = acc.create_user(sf, "other@x.com", "password12")
    other_org = acc.ensure_personal_org(sf, other_user["id"], other_user["email"])
    other_agent = acc.create_agent(sf, other_org, other_user["id"], "theirs", "coding/reader")
    _emit(sf, mine, "NOTIFY_ACT", True)
    for _ in range(5):
        _emit(sf, other_agent["id"], "DENY", False, "web-egress", "data-exfiltration")

    body = client.get("/api/governance/summary?days=30").json()
    assert body["actions_governed"] == 1  # only my org's one event
    assert body["exfil_blocked"] == 0


def test_governance_summary_requires_auth(ctx) -> None:
    client, sf, acc, _ = ctx
    client.cookies.clear()
    assert client.get("/api/governance/summary").status_code == 401
