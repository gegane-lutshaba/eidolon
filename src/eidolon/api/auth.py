"""Auth for the audit console + forensic endpoints (``/audit/*``, ``/replay``).

A single configured secret (``EIDOLON_AUDIT_TOKEN``) gates the ledger. It is
accepted two ways, so both humans and machines work:

- ``Authorization: Bearer <token>`` — for curl / CI / the JSON+CSV exports.
- an HttpOnly login cookie — set by ``POST /audit/login`` so the browser console
  works without embedding the token in every request.

Fail-closed in the spirit of EIDOLON's default-deny: with a token configured,
anything unauthenticated is rejected. With **no** token configured the endpoints
serve open (localhost-dev convenience) but log one loud warning — you must set
the token before exposing the service to a network.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request

from eidolon.config import Settings, get_settings

AUDIT_COOKIE = "eidolon_audit"

_log = logging.getLogger("eidolon.audit")
_warned = False


def audit_auth_enabled(settings: Settings | None = None) -> bool:
    return bool((settings or get_settings()).audit_token)


def _presented_token(request: Request) -> str | None:
    """The credential offered by the caller: Bearer header, else login cookie."""
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip()
    return request.cookies.get(AUDIT_COOKIE)


def token_matches(candidate: str | None, settings: Settings | None = None) -> bool:
    configured = (settings or get_settings()).audit_token
    if not configured or candidate is None:
        return False
    return secrets.compare_digest(candidate, configured)


def is_audit_authed(request: Request, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.audit_token:
        global _warned
        if not _warned:
            _log.warning(
                "audit endpoints are UNAUTHENTICATED — set EIDOLON_AUDIT_TOKEN to "
                "require a credential before exposing this service to a network."
            )
            _warned = True
        return True  # dev convenience; loudly warned exactly once
    return token_matches(_presented_token(request), settings)


def require_audit(request: Request) -> None:
    """FastAPI dependency for JSON/CSV forensic endpoints (401 on failure)."""
    if not is_audit_authed(request):
        raise HTTPException(
            status_code=401,
            detail="audit authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
