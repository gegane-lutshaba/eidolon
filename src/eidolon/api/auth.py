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
configured the platform runs OPEN for loopback callers only (localhost dev) and
logs one loud warning; any other caller is unauthenticated unless
``EIDOLON_OPEN_MODE=1`` deliberately opens it to the network.
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


# TCP peers treated as local in token-less mode. "testclient" is the peer name
# Starlette's in-process TestClient uses; it cannot arrive over a socket.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _is_loopback(request: Request) -> bool:
    """True iff the *socket peer* is local. Deliberately ignores X-Forwarded-For:
    behind a proxy the service is exposed, so it must not count as local."""
    host = request.client.host if request.client else ""
    return host in _LOOPBACK or host.startswith("127.")


def open_access(request: Request, settings: Settings | None = None) -> bool:
    """Token-less mode grants access only to loopback callers, or to everyone
    when EIDOLON_OPEN_MODE=1 is set on purpose."""
    settings = settings or get_settings()
    if auth_enabled(settings):
        return False
    global _warned
    if not _warned:
        _log.warning(
            "EIDOLON is running OPEN — no EIDOLON_ADMIN_TOKEN / EIDOLON_AUDIT_TOKEN set. "
            "Only loopback callers get access%s. Set an admin token before exposing it.",
            "" if not settings.open_mode else " (EIDOLON_OPEN_MODE=1: EVERY caller is admin)",
        )
        _warned = True
    return settings.open_mode or _is_loopback(request)


def current_role(request: Request, settings: Settings | None = None) -> str | None:
    """The caller's effective role. Token-less: admin for loopback callers (or all
    callers under EIDOLON_OPEN_MODE=1), otherwise unauthenticated."""
    settings = settings or get_settings()
    if not auth_enabled(settings):
        return "admin" if open_access(request, settings) else None
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
           "/roadmap", "/contact", "/versus/stats", "/showcase", "/console",
    "/og.png", "/favicon.svg", "/apple-touch-icon.png", "/icon-512.png",
    "/site.webmanifest", "/auth/config", "/auth/sso/login", "/auth/sso/callback"}

# Paths that require a signed-in USER (or the operator admin): the product app.
_USER_PREFIX = ("/app", "/api/")

# GET paths available to the read-only auditor role (and thus admin too):
# the forensic surface, the showcase, and mission control (viewing). The
# control plane (delegations, approvals, skills, kill switch) is admin-only.
_AUDITOR_GET_EXACT = {"/replay", "/gateways"}
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
    if path.startswith("/gate/"):
        return None  # coding-agent hook endpoints self-authenticate (agent key)
    if path.startswith(_USER_PREFIX) or path == "/auth/change-password":
        return "user"
    if path.startswith("/certified"):
        return None  # public certificates + badges + directory
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


def is_valid_gateway_key(candidate: str | None, settings: Settings | None = None,
                         request: Request | None = None) -> bool:
    """Machine credential for event ingest: a configured gateway key, or the
    admin token. Token-less dev mode accepts ingest from loopback callers (or
    anyone under EIDOLON_OPEN_MODE=1)."""
    settings = settings or get_settings()
    if not auth_enabled(settings) and not settings.gateway_keys:
        return settings.open_mode if request is None else open_access(request, settings)
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
