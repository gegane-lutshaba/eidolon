"""Auth on the forensic surface: /audit, its exports, and /replay.

Fail-closed when EIDOLON_AUDIT_TOKEN is set (Bearer header or login cookie);
open-with-warning when unset (localhost dev).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings
from eidolon.sage.port import Attestation, now_utc

TOKEN = "s3cret-audit-token"


@pytest.fixture
def audit_token(monkeypatch):
    """Set/clear EIDOLON_AUDIT_TOKEN and reset the settings cache around a test."""

    def _set(value: str | None) -> None:
        if value is None:
            monkeypatch.delenv("EIDOLON_AUDIT_TOKEN", raising=False)
        else:
            monkeypatch.setenv("EIDOLON_AUDIT_TOKEN", value)
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


# --- disabled (no token) -> open, dev convenience -----------------------
def test_open_when_no_token_configured(client, audit_token) -> None:
    audit_token(None)
    assert client.get("/audit").status_code == 200
    assert client.get("/audit/chain").status_code == 200
    assert client.get("/replay", params={"principal_id": "alice"}).status_code == 200


# --- enabled, no credential -> rejected / login -------------------------
def test_console_serves_login_when_unauthed(client, audit_token) -> None:
    audit_token(TOKEN)
    r = client.get("/audit")
    assert r.status_code == 200  # page renders...
    assert "Unlock" in r.text and "audit console" in r.text.lower()  # ...but it's the login


def test_forensic_endpoints_401_without_credential(client, audit_token) -> None:
    audit_token(TOKEN)
    assert client.get("/audit/chain").status_code == 401
    assert client.get("/replay", params={"principal_id": "alice"}).status_code == 401
    assert client.get("/audit/export.json", params={"principal_id": "alice"}).status_code == 401
    assert client.get("/audit/export.csv", params={"principal_id": "alice"}).status_code == 401


# --- enabled, Bearer header -> allowed ----------------------------------
def test_bearer_token_grants_access(client, audit_token) -> None:
    audit_token(TOKEN)
    h = {"Authorization": f"Bearer {TOKEN}"}
    assert client.get("/audit/chain", headers=h).status_code == 200
    assert client.get("/replay", params={"principal_id": "alice"}, headers=h).status_code == 200
    assert client.get("/audit/export.json", params={"principal_id": "alice"}, headers=h).status_code == 200


def test_wrong_bearer_token_rejected(client, audit_token) -> None:
    audit_token(TOKEN)
    h = {"Authorization": "Bearer nope"}
    assert client.get("/audit/chain", headers=h).status_code == 401


# --- login cookie flow (browser) ---------------------------------------
def test_login_sets_cookie_then_console_and_data_work(client, audit_token) -> None:
    audit_token(TOKEN)
    # bad token first
    assert client.post("/audit/login", json={"token": "wrong"}).status_code == 401

    r = client.post("/audit/login", json={"token": TOKEN})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "eidolon_audit" in r.cookies  # cookie issued (TestClient persists it)

    # now the console serves the real page and data flows (cookie auto-sent)
    assert "audit console" in client.get("/audit").text.lower()
    assert client.get("/audit/chain").status_code == 200
    assert client.get("/replay", params={"principal_id": "alice"}).status_code == 200


def test_logout_clears_cookie(client, audit_token) -> None:
    audit_token(TOKEN)
    client.post("/audit/login", json={"token": TOKEN})
    assert client.get("/audit/chain").status_code == 200
    client.post("/audit/logout")
    client.cookies.clear()
    assert client.get("/audit/chain").status_code == 401
