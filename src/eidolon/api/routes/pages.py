"""Static pages: the HTML shells the browser loads (data comes from the APIs).

Auth still applies: the app middleware gates by path (e.g. /live, /audit for
operators; /app for signed-in users). These handlers only serve files.
"""

from __future__ import annotations

import pathlib

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, Response

router = APIRouter()

_STATIC = pathlib.Path(__file__).resolve().parent.parent / "static"


@router.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    return (_STATIC / "login.html").read_text(encoding="utf-8")


@router.get("/certified", response_class=HTMLResponse)
def certified_directory() -> str:
    return (_STATIC / "certified.html").read_text(encoding="utf-8")


@router.get("/certified/{cert_id}", response_class=HTMLResponse)
def certificate_page(cert_id: str) -> str:
    return (_STATIC / "certificate.html").read_text(encoding="utf-8")


@router.get("/console/delegations", response_class=HTMLResponse)
def console_delegations() -> str:
    return (_STATIC / "console_delegations.html").read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
def landing() -> str:
    """The public landing page (retro-arcade)."""
    return (_STATIC / "landing.html").read_text(encoding="utf-8")


@router.get("/signup", response_class=HTMLResponse)
def signup_page() -> str:
    return (_STATIC / "signup.html").read_text(encoding="utf-8")


@router.get("/roadmap", response_class=HTMLResponse)
def roadmap_page() -> str:
    """The public roadmap — Gegane's boss run (what shipped, what's next)."""
    return (_STATIC / "roadmap.html").read_text(encoding="utf-8")


@router.get("/portal", response_class=HTMLResponse)
def portal_page() -> str:
    """The ONYX ARCADE portal served at the root domain (via Caddy rewrite)."""
    return (_STATIC / "portal.html").read_text(encoding="utf-8")


@router.get("/paper", response_class=HTMLResponse)
def paper_page() -> str:
    """The white paper (revision 2) as an in-theme arcade page (rendered client-side)."""
    return (_STATIC / "paper.html").read_text(encoding="utf-8")


@router.get("/og.png")
def og_image() -> Response:
    """Arcade link-preview card (Open Graph / X)."""

    return FileResponse(_STATIC / "og.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/contact", response_class=HTMLResponse)
def contact_page() -> str:
    """JOIN THE CO-OP — collaboration/contact funnel."""
    return (_STATIC / "contact.html").read_text(encoding="utf-8")


@router.get("/app", response_class=HTMLResponse)
def app_page() -> str:
    """The user product: agents, connect, gamified mission control."""
    return (_STATIC / "app.html").read_text(encoding="utf-8")


@router.get("/versus", response_class=HTMLResponse)
def versus_page() -> str:
    return (_STATIC / "versus.html").read_text(encoding="utf-8")


@router.get("/live", response_class=HTMLResponse)
def live_page() -> str:
    """Mission control: live feed, agent cards, approvals, kill switch."""
    return (_STATIC / "live.html").read_text(encoding="utf-8")


@router.get("/audit", response_class=HTMLResponse)
def audit_console() -> str:
    """Session replay, chain integrity, export."""
    return (_STATIC / "audit.html").read_text(encoding="utf-8")
