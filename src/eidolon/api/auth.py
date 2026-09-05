"""Operator auth for the self-hosted platform (single tenant, two roles).

Two configured secrets grant two roles:

    EIDOLON_ADMIN_TOKEN -> "admin"   : full control plane (mint/revoke, approve…)
    EIDOLON_AUDIT_TOKEN -> "auditor" : read-only forensic surface (/audit, /replay)

Accepted as ``Authorization: Bearer <token>`` (CI / SDK) or an HttpOnly session
cookie set by ``POST /login`` (browser). The role is re-derived from the token
on every request — stateless, so rotating a token in config immediately
invalidates its live sessions.

Gating is centralized in :func:`required_role` (a path/method policy) and applied
by one middleware, rather than sprinkled across endpoints.

Fail-closed in the spirit of default-deny: with any token configured,
unauthenticated or under-privileged access is rejected. With **no** token
configured the platform runs OPEN (localhost dev only) and logs one loud warning.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Request

from eidolon.config import Settings, get_settings

SESSION_COOKIE = "eidolon_session"
USER_COOKIE = "eidolon_user"

_RANK = {"auditor": 1, "admin": 2}
_log = logging.getLogger("eidolon.auth")
_warned = False


# -- token → role --------------------------------------------------------
def _token_roles(settings: Settings) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if settings.admin_token:
        pairs.append((settings.admin_token, "admin"))
    if settings.audit_token:
        pairs.append((settings.audit_token, "auditor"))
    return pairs


def auth_enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.admin_token or settings.audit_token)


def role_for_token(candidate: str | None, settings: Settings | None = None) -> str | None:
    """Highest role a presented token grants, or None. Constant-time compare."""
    if candidate is None:
        return None
    settings = settings or get_settings()
    best: str | None = None
    for token, role in _token_roles(settings):
        if secrets.compare_digest(candidate, token) and (best is None or _RANK[role] > _RANK[best]):
            best = role
    return best


def _presented(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def current_role(request: Request, settings: Settings | None = None) -> str | None:
    """The caller's effective role. In open mode (no tokens) everyone is admin."""
    settings = settings or get_settings()
    if not auth_enabled(settings):
        global _warned
        if not _warned:
            _log.warning(
                "EIDOLON is running OPEN — no EIDOLON_ADMIN_TOKEN / EIDOLON_AUDIT_TOKEN set. "
                "Set at least an admin token before exposing this service to a network."
            )
            _warned = True
        return "admin"
    return role_for_token(_presented(request), settings)


def has_role(role: str | None, minimum: str) -> bool:
    return role is not None and _RANK[role] >= _RANK[minimum]


# -- centralized path policy --------------------------------------------
# Exact paths that need no auth at all. /ingest/events authenticates itself
# (gateway API key — a machine credential, not an operator role). The landing
# page + user signup/login are public by design.
_PUBLIC = {"/health", "/ready", "/login", "/logout", "/whoami", "/favicon.ico",
           "/ingest/events", "/", "/signup", "/auth/signup", "/auth/login",
           "/auth/logout", "/stats/public", "/portal", "/paper", "/paper/content",
           "/contact", "/versus/stats"}

# Paths that require a signed-in USER (or the operator admin): the product app.
_USER_PREFIX = ("/app", "/api/")

# GET paths available to the read-only auditor role (and thus admin too):
# the forensic surface, the showcase, and mission control (viewing). The
# control plane (delegations, approvals, skills, kill switch) is admin-only.
_AUDITOR_GET_EXACT = {"/showcase", "/replay", "/gateways"}
_AUDITOR_GET_PREFIX = ("/audit", "/profiles", "/challenge", "/live")


def required_role(method: str, path: str) -> str | None:
    """The minimum role for (method, path). None = public, "user" = a signed-in
    account (or operator admin).

    Read/forensic surfaces are auditor+; everything else that mutates or drives
    the control plane is admin.
    """
    if path in _PUBLIC:
        return None
    if path == "/mcp" or path.startswith("/mcp/"):
        return None  # hosted MCP endpoint authenticates itself (agent gateway key)
    if path.startswith(_USER_PREFIX):
        return "user"
    if path.startswith("/challenge") or path.startswith("/versus"):
        # The break-the-gate demo + VERSUS mode are not control-plane mutations.
        # With EIDOLON_PUBLIC_CHALLENGE they are open to the internet
        # (rate-limited); otherwise auditor+ (operator preview).
        if get_settings().public_challenge:
            return None
        return "auditor"
    if method in ("GET", "HEAD"):
        if path in _AUDITOR_GET_EXACT or path.startswith(_AUDITOR_GET_PREFIX):
            return "auditor"
    return "admin"


def is_valid_gateway_key(candidate: str | None, settings: Settings | None = None) -> bool:
    """Machine credential for event ingest: a configured gateway key, or the
    admin token. In fully-open dev mode (no tokens at all) ingest is open too."""
    settings = settings or get_settings()
    if not auth_enabled(settings) and not settings.gateway_keys:
        return True  # localhost dev, everything open
    if candidate is None:
        return False
    keys = [k.strip() for k in (settings.gateway_keys or "").split(",") if k.strip()]
    if settings.admin_token:
        keys.append(settings.admin_token)
    return any(secrets.compare_digest(candidate, k) for k in keys)


def client_ip(request: Request, settings: Settings | None = None) -> str:
    """The caller's IP for rate limiting. Behind a trusted reverse proxy
    (EIDOLON_TRUST_PROXY_HEADERS) use the first X-Forwarded-For hop — otherwise
    every visitor would share the proxy container's IP. Off by default: the
    header is spoofable when the app is directly exposed."""
    settings = settings or get_settings()
    if settings.trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"
