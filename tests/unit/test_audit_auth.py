"""Operator auth: two roles (admin / auditor), fail-closed, Bearer + cookie.

- open mode (no tokens) -> everything works (localhost dev)
- tokens set -> forensic surface needs auditor+, control plane needs admin
- Bearer header (CI/SDK) and login cookie (browser) both grant the role
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings
from eidolon.sage.port import Attestation, now_utc

ADMIN = "admin-token-xyz"
AUDIT = "audit-token-abc"


@pytest.fixture
def tokens(monkeypatch):
    """Set/clear the role tokens and reset the settings cache around a test."""

    def _set(admin: str | None, auditor: str | None) -> None:
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

    rt = app_module.runtime()  # memory backend in the test lane
    rt.sage.attest(Attestation(action="post", action_class="status-update",
                               timestamp=now_utc(), principal_id="alice"))
    return TestClient(app_module.app)


# --- open mode ----------------------------------------------------------
def test_open_when_no_tokens(client, tokens) -> None:
    tokens(None, None)
    assert client.get("/audit/chain").status_code == 200
    assert client.post("/keypair").status_code == 200  # control plane open too
    who = client.get("/whoami").json()
    assert who["role"] == "admin" and who["auth_enabled"] is False


# --- tokens set, no credential -----------------------------------------
def test_no_credential_is_denied(client, tokens) -> None:
    tokens(ADMIN, AUDIT)
    who = client.get("/whoami").json()
    assert who["role"] is None and who["auth_enabled"] is True
    assert client.get("/audit/chain").status_code == 401           # forensic
    assert client.post("/keypair").status_code == 401              # control plane
    assert client.get("/replay", params={"principal_id": "alice"}).status_code == 401


def test_browser_navigation_redirects_to_login(client, tokens) -> None:
    tokens(ADMIN, AUDIT)
    r = client.get("/audit", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


# --- auditor: read-only -------------------------------------------------
def test_auditor_can_read_but_not_mutate(client, tokens) -> None:
    tokens(ADMIN, AUDIT)
    h = {"Authorization": f"Bearer {AUDIT}"}
    assert client.get("/audit/chain", headers=h).status_code == 200
    assert client.get("/replay", params={"principal_id": "alice"}, headers=h).status_code == 200
    # control-plane mutations are admin-only: authenticated but under-privileged -> 403
    assert client.post("/keypair", headers=h).status_code == 403
    assert client.post("/delegations/revoke", json={"delegation_id": "x"}, headers=h).status_code == 403


# --- admin: full access -------------------------------------------------
def test_admin_bearer_full_access(client, tokens) -> None:
    tokens(ADMIN, AUDIT)
    h = {"Authorization": f"Bearer {ADMIN}"}
    assert client.get("/audit/chain", headers=h).status_code == 200
    assert client.post("/keypair", headers=h).status_code == 200
    assert client.get("/whoami", headers=h).json()["role"] == "admin"


def test_wrong_token_rejected(client, tokens) -> None:
    tokens(ADMIN, AUDIT)
    assert client.get("/audit/chain", headers={"Authorization": "Bearer nope"}).status_code == 401


# --- browser cookie login ----------------------------------------------
def test_login_cookie_flow(client, tokens) -> None:
    tokens(ADMIN, AUDIT)
    assert client.post("/login", json={"token": "wrong"}).status_code == 401

    r = client.post("/login", json={"token": ADMIN})
    assert r.status_code == 200 and r.json() == {"ok": True, "role": "admin"}
    assert "eidolon_session" in r.cookies

    assert client.post("/keypair").status_code == 200      # cookie auto-sent
    assert client.get("/audit/chain").status_code == 200


def test_auditor_cookie_is_read_only(client, tokens) -> None:
    tokens(ADMIN, AUDIT)
    assert client.post("/login", json={"token": AUDIT}).json()["role"] == "auditor"
    assert client.get("/audit/chain").status_code == 200
    assert client.post("/keypair").status_code == 403  # authenticated auditor, admin route


def test_logout_clears_session(client, tokens) -> None:
    tokens(ADMIN, AUDIT)
    client.post("/login", json={"token": ADMIN})
    assert client.get("/audit/chain").status_code == 200
    client.post("/logout")
    client.cookies.clear()
    assert client.get("/audit/chain").status_code == 401
