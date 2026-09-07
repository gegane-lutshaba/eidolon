"""Minimal OIDC (Authorization Code) client for staff SSO.

Back-channel calls go over TLS to the operator-configured issuer's token and
userinfo endpoints, so we trust the claims returned from ``userinfo`` without
verifying the id_token signature ourselves (no JWKS/JWT-crypto dependency). That
is sufficient to provision a session: the code is exchanged directly with the
trusted token endpoint, and the access token is presented to that same issuer's
userinfo endpoint.

Endpoints (mounted in app.py):
    GET /auth/sso/login    -> redirect to the IdP
    GET /auth/sso/callback -> exchange code, provision user, open session
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from eidolon.config import Settings

_TIMEOUT = 8.0
_DISCOVERY_TTL = 3600.0
_disc_cache: dict[str, tuple[float, dict]] = {}


def enabled(settings: Settings) -> bool:
    return bool(settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret)


def redirect_uri(settings: Settings) -> str:
    base = (settings.public_url or "http://localhost:8000").rstrip("/")
    return f"{base}/auth/sso/callback"


def discover(settings: Settings) -> dict:
    """OIDC discovery document (cached), giving the authorize/token/userinfo URLs."""
    issuer = (settings.oidc_issuer or "").rstrip("/")
    now = time.monotonic()
    hit = _disc_cache.get(issuer)
    if hit and now - hit[0] < _DISCOVERY_TTL:
        return hit[1]
    url = f"{issuer}/.well-known/openid-configuration"
    with httpx.Client(timeout=_TIMEOUT) as c:
        doc = c.get(url).raise_for_status().json()
    _disc_cache[issuer] = (now, doc)
    return doc


def authorize_url(settings: Settings, state: str) -> str:
    from urllib.parse import urlencode

    doc = discover(settings)
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri(settings),
        "scope": settings.oidc_scopes,
        "state": state,
    }
    return f"{doc['authorization_endpoint']}?{urlencode(params)}"


def exchange_code(settings: Settings, code: str) -> dict:
    doc = discover(settings)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(settings),
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
    }
    with httpx.Client(timeout=_TIMEOUT) as c:
        return c.post(doc["token_endpoint"], data=data,
                      headers={"Accept": "application/json"}).raise_for_status().json()


def userinfo(settings: Settings, access_token: str) -> dict:
    doc = discover(settings)
    with httpx.Client(timeout=_TIMEOUT) as c:
        return c.get(doc["userinfo_endpoint"],
                     headers={"Authorization": f"Bearer {access_token}"}).raise_for_status().json()


def claims_to_email(claims: dict[str, Any]) -> str | None:
    """Extract a verified email from userinfo claims. If the IdP reports
    email_verified explicitly and it is false, reject."""
    email = (claims.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return None
    if claims.get("email_verified") is False:
        return None
    return email


def domain_allowed(settings: Settings, email: str) -> bool:
    allow = [d.strip().lower() for d in (settings.oidc_allowed_domains or "").split(",") if d.strip()]
    if not allow:
        return True
    domain = email.rsplit("@", 1)[-1]
    return domain in allow
