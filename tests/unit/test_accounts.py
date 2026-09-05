"""User accounts + agents: signup/login/session lifecycle, agent creation with
per-agent gateway keys, ownership isolation (a user only ever sees their own
agents/events; a per-agent key is pinned to its own gateway_id on ingest).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.api import accounts as accounts_svc
from eidolon.config import get_settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'acc.db'}")
    monkeypatch.setenv("EIDOLON_ADMIN_TOKEN", "admin-t")
    monkeypatch.setenv("EIDOLON_GATEWAY_KEYS", "op-key")
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module

    app_module._runtime = None
    app_module._live_sf = None
    app_module._login_hits.clear()
    yield TestClient(app_module.app)
    app_module._runtime = None
    app_module._live_sf = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def _signup(client, email="ada@example.com", password="hunter2hunter2"):
    r = client.post("/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


# --- password hashing ---------------------------------------------------
def test_password_hash_roundtrip() -> None:
    h = accounts_svc.hash_password("correct horse")
    assert h.startswith("scrypt$") and "correct horse" not in h
    assert accounts_svc.verify_password("correct horse", h)
    assert not accounts_svc.verify_password("wrong", h)


# --- signup / login / session -------------------------------------------
def test_signup_login_logout(client) -> None:
    _signup(client)
    me = client.get("/api/me").json()
    assert me["admin"] is False and me["email"] == "ada@example.com"
    assert me["org"]["personal"] is True and me["role"] == "owner"  # personal org on signup

    client.post("/auth/logout")
    client.cookies.clear()
    assert client.get("/api/me").status_code == 401

    r = client.post("/auth/login", json={"email": "ada@example.com", "password": "hunter2hunter2"})
    assert r.status_code == 200
    assert client.get("/api/me").json()["email"] == "ada@example.com"


def test_signup_validation_and_duplicates(client) -> None:
    assert client.post("/auth/signup", json={"email": "bad", "password": "hunter2hunter2"}).status_code == 400
    assert client.post("/auth/signup", json={"email": "a@b.co", "password": "short"}).status_code == 400
    _signup(client)
    client.cookies.clear()
    assert client.post("/auth/signup", json={"email": "ada@example.com",
                                             "password": "hunter2hunter2"}).status_code == 400


def test_wrong_password_rejected(client) -> None:
    _signup(client)
    client.cookies.clear()
    assert client.post("/auth/login", json={"email": "ada@example.com",
                                            "password": "not-the-password"}).status_code == 401


def test_invite_code_gate(client, monkeypatch) -> None:
    monkeypatch.setenv("EIDOLON_INVITE_CODE", "friends-only")
    get_settings.cache_clear()
    import eidolon.api.app as app_module

    app_module._runtime = None  # pick up new settings
    r = client.post("/auth/signup", json={"email": "x@y.co", "password": "hunter2hunter2"})
    assert r.status_code == 403
    r = client.post("/auth/signup", json={"email": "x@y.co", "password": "hunter2hunter2",
                                          "invite_code": "friends-only"})
    assert r.status_code == 200


# --- agents + ownership --------------------------------------------------
def test_agent_lifecycle_and_connect(client) -> None:
    _signup(client)
    r = client.post("/api/agents", json={"name": "claude-code", "preset": "builder"})
    assert r.status_code == 200
    agent = r.json()
    assert agent["gateway_key"].startswith("egk_") and agent["rank"] == "DRAFTER"

    listed = client.get("/api/agents").json()
    assert [a["name"] for a in listed] == ["claude-code"]
    assert listed[0]["connected"] is False and listed[0]["blocks"] == 0

    conn = client.get(f"/api/agents/{agent['id']}/connect").json()
    assert agent["gateway_key"] in conn["gateway_yaml"]
    assert agent["id"] in conn["gateway_yaml"]
    # three doors: managed / agent-setup / self-hosted
    assert agent["gateway_key"] in conn["managed"]["claude_code_cmd"]
    assert "EIDOLON setup" in conn["agent_setup_md"]
    assert "uvx --from git+" in conn["selfhost"]["gateway_cmd"]

    assert client.delete(f"/api/agents/{agent['id']}").json() == {"deleted": agent["id"]}
    assert client.get("/api/agents").json() == []


def test_users_cannot_see_each_others_agents(client) -> None:
    _signup(client, "ada@example.com")
    a = client.post("/api/agents", json={"name": "adas-agent"}).json()
    client.post("/auth/logout")
    client.cookies.clear()

    _signup(client, "bob@example.com")
    assert client.get("/api/agents").json() == []                       # bob sees nothing
    assert client.get(f"/api/agents/{a['id']}/connect").status_code == 404
    assert client.post(f"/api/agents/{a['id']}/kill").status_code == 404
    assert client.delete(f"/api/agents/{a['id']}").status_code == 404


def test_agent_key_ingest_is_pinned_to_own_gateway(client) -> None:
    _signup(client)
    agent = client.post("/api/agents", json={"name": "claude-code"}).json()
    # report with the agent key but a SPOOFED gateway_id -> pinned back
    r = client.post("/ingest/events", json={
        "gateway_id": "someone-elses-gw", "tool": "read_file",
        "level": "AUTONOMOUS_ACT", "allowed": True},
        headers={"Authorization": f"Bearer {agent['gateway_key']}"})
    assert r.status_code == 200
    feed = client.get("/api/feed/recent").json()
    assert len(feed) == 1 and feed[0]["gateway_id"] == agent["id"]      # pinned + owned
    assert feed[0]["agent"] == "claude-code"

    listed = client.get("/api/agents").json()
    assert listed[0]["connected"] is True and listed[0]["events"] == 1


def test_feed_is_ownership_filtered(client) -> None:
    _signup(client, "ada@example.com")
    ada_agent = client.post("/api/agents", json={"name": "adas"}).json()
    client.post("/ingest/events", json={"gateway_id": "x", "tool": "t1",
                                        "level": "DENY", "allowed": False},
                headers={"Authorization": f"Bearer {ada_agent['gateway_key']}"})
    client.post("/auth/logout")
    client.cookies.clear()

    _signup(client, "bob@example.com")
    bob_agent = client.post("/api/agents", json={"name": "bobs"}).json()
    client.post("/ingest/events", json={"gateway_id": "x", "tool": "t2",
                                        "level": "DENY", "allowed": False},
                headers={"Authorization": f"Bearer {bob_agent['gateway_key']}"})

    bob_feed = client.get("/api/feed/recent").json()
    assert [e["tool"] for e in bob_feed] == ["t2"]                      # only bob's
    assert client.get("/api/agents").json()[0]["blocks"] == 1           # gamified stat


def test_deleted_agent_key_stops_working(client) -> None:
    _signup(client)
    agent = client.post("/api/agents", json={"name": "temp"}).json()
    client.delete(f"/api/agents/{agent['id']}")
    r = client.post("/ingest/events", json={"gateway_id": agent["id"], "tool": "t",
                                            "level": "DENY", "allowed": False},
                    headers={"Authorization": f"Bearer {agent['gateway_key']}"})
    assert r.status_code == 401                                          # revoked


def test_app_pages_gated_and_public_pages_open(client) -> None:
    assert client.get("/").status_code == 200            # landing is public
    assert client.get("/signup").status_code == 200
    r = client.get("/app", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/signup"
    _signup(client)
    assert client.get("/app").status_code == 200


def test_contact_lead_capture_and_admin_inbox(client) -> None:
    # public submit
    r = client.post("/contact", json={"handle": "@dev", "email": "dev@x.co",
                                      "interest": "collaborate", "message": "let's build"})
    assert r.status_code == 200 and r.json()["ok"]
    # validation: needs a way to reach + a message
    assert client.post("/contact", json={"message": ""}).status_code == 400
    # admin inbox
    leads = client.get("/api/leads", headers={"Authorization": "Bearer admin-t"}).json()
    assert any(x["email"] == "dev@x.co" for x in leads)
    # non-admin cannot read leads
    client.post("/auth/signup", json={"email": "u@x.co", "password": "strongpass123"})
    assert client.get("/api/leads").status_code == 403


def test_expanded_gallery_kinds(client) -> None:
    client.post("/auth/signup", json={"email": "fin@x.co", "password": "strongpass123"})
    g = client.get("/api/gallery").json()
    assert {"coding", "research", "comms", "devops", "data", "support", "finance"} <= set(g)
    # a finance agent's yaml holds payment tools (commit-action), never auto-acts them
    a = client.post("/api/agents", json={"name": "ap-bot", "preset": "finance/reader"}).json()
    conn = client.get(f"/api/agents/{a['id']}/connect").json()
    assert "wire_funds" in conn["gateway_yaml"] and "read_ledger" in conn["gateway_yaml"]


# --- teams / orgs -------------------------------------------------------
def test_personal_org_and_agent_scoping(client) -> None:
    _signup(client)
    orgs = client.get("/api/orgs").json()
    assert len(orgs) == 1 and orgs[0]["personal"] and orgs[0]["role"] == "owner"
    a = client.post("/api/agents", json={"name": "cc", "preset": "coding/builder"}).json()
    assert a["id"] in [x["id"] for x in client.get("/api/agents").json()]


def test_invite_join_and_cross_org_isolation(client) -> None:
    # owner (ada) makes an agent + an admin invite
    _signup(client, "ada@example.com")
    ada_agent = client.post("/api/agents", json={"name": "adas"}).json()
    code = client.post("/api/orgs/invite", json={"role": "member"}).json()["code"]
    client.post("/auth/logout")
    client.cookies.clear()

    # bob signs up (own personal org) — cannot see ada's agent
    _signup(client, "bob@example.com")
    assert client.get("/api/agents").json() == []
    # bob joins ada's org via the invite -> now sees the shared agent
    joined = client.post("/api/orgs/join", json={"code": code})
    assert joined.status_code == 200
    names = [x["name"] for x in client.get("/api/agents").json()]
    assert "adas" in names
    assert client.get(f"/api/agents/{ada_agent['id']}/connect").status_code == 200


def test_auditor_is_read_only(client) -> None:
    _signup(client, "ada@example.com")
    code = client.post("/api/orgs/invite", json={"role": "auditor"}).json()["code"]
    client.post("/auth/logout")
    client.cookies.clear()
    _signup(client, "aud@example.com")
    client.post("/api/orgs/join", json={"code": code})
    # switch into ada's org (join set the cookie already)
    assert client.get("/api/agents").status_code == 200          # can view
    r = client.post("/api/agents", json={"name": "x"})
    assert r.status_code == 403                                   # cannot create


def test_switch_requires_membership(client) -> None:
    _signup(client, "ada@example.com")
    assert client.post("/api/orgs/switch", json={"org_id": "org-nope"}).status_code == 403
