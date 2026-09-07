"""SSO (OIDC) staff login: /auth/config, /auth/sso/login, /auth/sso/callback,
and directory-provisioning via find_or_create_sso_user. The IdP HTTP calls are
monkeypatched — no network."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings


def _reset(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'sso.db'}")
    monkeypatch.setenv("EIDOLON_PUBLIC_URL", "https://eidolon.test")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module

    app_module._runtime = None
    app_module._live_sf = None
    return app_module, db_mod


@pytest.fixture
def sso_env(monkeypatch, tmp_path):
    app_module, db_mod = _reset(
        monkeypatch, tmp_path,
        EIDOLON_OIDC_ISSUER="https://idp.example",
        EIDOLON_OIDC_CLIENT_ID="cid", EIDOLON_OIDC_CLIENT_SECRET="secret",
        EIDOLON_OIDC_BUTTON_LABEL="Okta")
    from eidolon.api import sso

    monkeypatch.setattr(sso, "discover", lambda s: {
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo"})
    yield TestClient(app_module.app), sso, monkeypatch
    app_module._runtime = None
    app_module._live_sf = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def test_config_reports_sso_disabled(monkeypatch, tmp_path) -> None:
    app_module, db_mod = _reset(monkeypatch, tmp_path)
    c = TestClient(app_module.app)
    cfg = c.get("/auth/config").json()
    assert cfg["sso"] is False
    assert c.get("/auth/sso/login", follow_redirects=False).status_code == 404
    app_module._runtime = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def test_config_reports_sso_enabled(sso_env) -> None:
    c, _sso, _mp = sso_env
    cfg = c.get("/auth/config").json()
    assert cfg["sso"] is True and cfg["sso_label"] == "Okta"


def test_login_redirects_to_idp_with_state(sso_env) -> None:
    c, _sso, _mp = sso_env
    r = c.get("/auth/sso/login", follow_redirects=False)
    assert r.status_code == 307
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["https://eidolon.test/auth/sso/callback"]
    assert "eidolon_sso_state" in r.cookies
    assert q["state"][0] == r.cookies["eidolon_sso_state"]


def _do_login(c):
    r = c.get("/auth/sso/login", follow_redirects=False)
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0]


def test_callback_provisions_and_signs_in(sso_env) -> None:
    c, sso, mp = sso_env
    mp.setattr(sso, "exchange_code", lambda s, code: {"access_token": "at"})
    mp.setattr(sso, "userinfo", lambda s, tok: {"email": "Dev@Example.com", "email_verified": True})
    state = _do_login(c)
    r = c.get(f"/auth/sso/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app"
    # session established -> the product API now recognizes the user
    me = c.get("/api/me").json()
    assert me["email"] == "dev@example.com"


def test_callback_rejects_bad_state(sso_env) -> None:
    c, sso, mp = sso_env
    mp.setattr(sso, "exchange_code", lambda s, code: {"access_token": "at"})
    mp.setattr(sso, "userinfo", lambda s, tok: {"email": "x@example.com"})
    _do_login(c)  # sets a state cookie
    r = c.get("/auth/sso/callback?code=abc&state=WRONG", follow_redirects=False)
    assert r.status_code == 303 and "sso_error=bad_state" in r.headers["location"]


def test_callback_enforces_allowed_domain(monkeypatch, tmp_path) -> None:
    app_module, db_mod = _reset(
        monkeypatch, tmp_path,
        EIDOLON_OIDC_ISSUER="https://idp.example", EIDOLON_OIDC_CLIENT_ID="cid",
        EIDOLON_OIDC_CLIENT_SECRET="secret", EIDOLON_OIDC_ALLOWED_DOMAINS="corp.example")
    from eidolon.api import sso

    monkeypatch.setattr(sso, "discover", lambda s: {
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "userinfo_endpoint": "https://idp.example/userinfo"})
    monkeypatch.setattr(sso, "exchange_code", lambda s, code: {"access_token": "at"})
    monkeypatch.setattr(sso, "userinfo", lambda s, tok: {"email": "outsider@gmail.com", "email_verified": True})
    c = TestClient(app_module.app)
    state = parse_qs(urlparse(c.get("/auth/sso/login", follow_redirects=False)
                             .headers["location"]).query)["state"][0]
    r = c.get(f"/auth/sso/callback?code=abc&state={state}", follow_redirects=False)
    assert "sso_error=domain_not_allowed" in r.headers["location"]
    app_module._runtime = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def test_find_or_create_sso_user_shared_org(monkeypatch, tmp_path) -> None:
    app_module, db_mod = _reset(monkeypatch, tmp_path)
    from eidolon.api import accounts as acc

    sf = app_module._live_store()
    a = acc.find_or_create_sso_user(sf, "a@corp.example", "Corp")
    b = acc.find_or_create_sso_user(sf, "b@corp.example", "Corp")
    again = acc.find_or_create_sso_user(sf, "a@corp.example", "Corp")
    assert a["created"] and b["created"] and not again["created"]
    # both users are members of the same shared org; first is owner
    orgs_a = {o["name"]: o["role"] for o in acc.orgs_for_user(sf, a["id"])}
    orgs_b = {o["name"]: o["role"] for o in acc.orgs_for_user(sf, b["id"])}
    assert orgs_a.get("Corp") == "owner"
    assert orgs_b.get("Corp") == "member"
    app_module._runtime = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
