"""Compliance packs: an org/date-range hash-sealed evidence bundle assembled
from the real governed-action record, with a control mapping + ledger status.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'comp.db'}")
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


def _agent_with_events(client):
    client.post("/auth/signup", json={"email": "ada@example.com", "password": "strongpass123"})
    agent = client.post("/api/agents", json={"name": "cc", "preset": "coding/operative"}).json()
    h = {"Authorization": f"Bearer {agent['gateway_key']}"}
    for tool, level, allowed in [("read_file", "AUTONOMOUS_ACT", True),
                                 ("wire_funds", "DENY", False),
                                 ("delete_database", "KILLED", False)]:
        client.post("/ingest/events", json={"gateway_id": "x", "tool": tool,
                                            "level": level, "allowed": allowed}, headers=h)
    return agent


def test_summary_counts_and_controls(client) -> None:
    _agent_with_events(client)
    d = client.get("/api/compliance/summary").json()
    assert d["kind"] == "eidolon.compliance-pack.v1"
    s = d["summary"]
    assert s["actions_governed"] == 3 and s["blocked"] == 2       # DENY + KILLED
    assert s["by_outcome"]["DENY"] == 1 and s["by_outcome"]["KILLED"] == 1
    assert any(c["soc2"] and c["eu_ai_act"] for c in d["controls"])  # mapping present
    assert "attestations" not in d                                # summary is lighter
    assert d["bundle_hash"]


def test_downloadable_bundle_is_sealed(client) -> None:
    _agent_with_events(client)
    r = client.get("/api/compliance/report.json")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert len(body["attestations"]) == 3
    # bundle_hash seals the payload: recompute over the rest
    from eidolon.common.canonical import content_hash

    sealed = dict(body)
    h = sealed.pop("bundle_hash")
    assert content_hash(sealed) == h


def test_scoped_to_org_agents_only(client) -> None:
    _agent_with_events(client)                    # ada's org has 3 events
    client.post("/auth/logout")
    client.cookies.clear()
    client.post("/auth/signup", json={"email": "bob@example.com", "password": "strongpass123"})
    d = client.get("/api/compliance/summary").json()
    assert d["summary"]["actions_governed"] == 0  # bob's fresh org: nothing


def test_retention_is_admin_only(client) -> None:
    client.post("/auth/signup", json={"email": "ada@example.com", "password": "strongpass123"})
    assert client.post("/api/orgs/retention", json={"days": 30}).json()["retention_days"] == 30
    # auditor cannot set retention
    code = client.post("/api/orgs/invite", json={"role": "auditor"}).json()["code"]
    client.post("/auth/logout")
    client.cookies.clear()
    client.post("/auth/signup", json={"email": "aud@example.com", "password": "strongpass123"})
    client.post("/api/orgs/join", json={"code": code})
    assert client.post("/api/orgs/retention", json={"days": 10}).status_code == 403
    # but can still read the compliance summary (auditor+)
    assert client.get("/api/compliance/summary").status_code == 200
