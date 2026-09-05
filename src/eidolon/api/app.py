"""FastAPI app exposing the core seams (PRD §6).

Endpoints map directly onto the component interfaces:
    POST /delegations/mint       -> THEMIS.mint
    POST /delegations/attenuate  -> THEMIS.attenuate
    POST /delegations/revoke     -> THEMIS.revoke
    POST /heartbeat              -> THEMIS.heartbeat
    POST /resolve                -> KAIROS.resolve (the gate)
    GET  /replay                 -> HORKOS.replay
    POST /capture/ingest         -> capture.ingest
    GET  /profiles/{id}          -> ProfileLoader.load
    POST /skills                 -> SkillLibrary.save
    GET  /skills                 -> SkillLibrary.load (relevant)
    POST /skills/run             -> SkillExecutor.run (subordinate to KAIROS)
    POST /coaching/report        -> Coach.coach (read-only, decoupled)

This is a thin transport layer; all invariants live in the components.
"""

from __future__ import annotations

import pathlib
import time

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from eidolon.api import accounts as accounts_svc
from eidolon.api import audit as audit_svc
from eidolon.api import live as live_svc
from eidolon.api.auth import (
    SESSION_COOKIE,
    USER_COOKIE,
    auth_enabled,
    client_ip,
    current_role,
    has_role,
    is_valid_gateway_key,
    required_role,
    role_for_token,
)
from eidolon.basanos.certify import Certificate
from eidolon.capture import ConsentGrant, connect, ingest, ingest_all, known_sources
from eidolon.coaching import Aspiration, Coach
from eidolon.common import crypto
from eidolon.common.errors import AttenuationError, EidolonError
from eidolon.escalation import EscalationQueue
from eidolon.profile import ProfileLoader
from eidolon.runtime import Runtime, build_runtime
from eidolon.sage.port import ReplayFilter
from eidolon.skills import Skill, SkillExecutor, SkillLibrary
from eidolon.themis.types import Delegation, MintParams
from eidolon.types import Action, Context

app = FastAPI(title="EIDOLON", version="0.1.0")

_STATIC = pathlib.Path(__file__).parent / "static"

_runtime: Runtime | None = None
_escalations: EscalationQueue | None = None
_login_hits: dict[str, list[float]] = {}  # ip -> recent login attempt times


def runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = build_runtime()
    return _runtime


def escalations() -> EscalationQueue:
    """The approval inbox — durable on the postgres backend."""
    global _escalations
    if _escalations is None:
        if runtime().settings.sage_backend == "postgres":
            from eidolon.escalation import PostgresEscalationQueue

            _escalations = PostgresEscalationQueue()
        else:
            _escalations = EscalationQueue()
    return _escalations


def current_user(request: Request) -> dict | None:
    """The signed-in account for this request (user-session cookie), if any."""
    token = request.cookies.get(USER_COOKIE)
    if not token:
        return None
    try:
        return accounts_svc.user_for_session(_live_store(), token)
    except Exception:  # noqa: BLE001 — no operational store = no user sessions
        return None


@app.middleware("http")
async def _gate_and_harden(request: Request, call_next):
    """Central auth gate (path/method policy) + baseline security headers."""
    needed = required_role(request.method, request.url.path)
    if needed == "user":
        # The product app: a signed-in user account, or the operator admin.
        if current_user(request) is None and not has_role(current_role(request), "admin"):
            wants_html = request.method in ("GET", "HEAD") and "text/html" in request.headers.get(
                "accept", ""
            )
            if wants_html:
                return RedirectResponse("/signup", status_code=303)
            return JSONResponse({"detail": "sign in required"}, status_code=401)
    elif needed is not None:
        role = current_role(request)
        if not has_role(role, needed):
            wants_html = request.method in ("GET", "HEAD") and "text/html" in request.headers.get(
                "accept", ""
            )
            if role is None:
                # Unauthenticated: send browsers to sign in, APIs a 401.
                if wants_html:
                    return RedirectResponse("/login", status_code=303)
                return JSONResponse(
                    {"detail": f"{needed} authentication required"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Authenticated but under-privileged: 403, never a login loop.
            return JSONResponse(
                {"detail": f"{needed} role required (you are {role})"}, status_code=403
            )
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if runtime().settings.session_cookie_secure:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return resp


@app.get("/health")
def health() -> dict:
    rt = runtime()
    return {
        "status": "ok",
        "sage_backend": rt.settings.sage_backend,
        "profile": f"{rt.profile.id}@{rt.profile.version}",
    }


@app.get("/ready")
def ready() -> Response:
    """Readiness: for the postgres backend, confirm a live DB round-trip."""
    rt = runtime()
    try:
        if rt.settings.sage_backend == "postgres":
            from sqlalchemy import text

            from eidolon.data.db import get_sessionmaker

            with get_sessionmaker()() as s:
                s.execute(text("SELECT 1"))
        return JSONResponse({"ready": True})
    except Exception as exc:  # noqa: BLE001 — readiness probe reports, never raises
        return JSONResponse({"ready": False, "error": str(exc)}, status_code=503)


# -- operator auth --------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    return (_STATIC / "login.html").read_text(encoding="utf-8")


@app.post("/login")
def login(request: Request, token: str = Body(..., embed=True)) -> Response:
    ip = client_ip(request)  # proxy-aware behind Caddy (EIDOLON_TRUST_PROXY_HEADERS)
    now = time.monotonic()
    hits = [t for t in _login_hits.get(ip, []) if now - t < 300.0]
    if len(hits) >= 10:
        raise HTTPException(status_code=429, detail="too many attempts; try again shortly")
    hits.append(now)
    _login_hits[ip] = hits

    role = role_for_token(token)
    if role is None:
        raise HTTPException(status_code=401, detail="invalid token")
    resp = JSONResponse({"ok": True, "role": role})
    resp.set_cookie(
        SESSION_COOKIE, token,
        httponly=True, samesite="lax",
        secure=runtime().settings.session_cookie_secure,
        max_age=43200, path="/",  # 12h
    )
    return resp


@app.post("/logout")
def logout() -> Response:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/whoami")
def whoami(request: Request) -> dict:
    user = current_user(request)
    return {"role": current_role(request), "auth_enabled": auth_enabled(),
            "user": {"email": user["email"]} if user else None}


# -- user accounts (the product app) --------------------------------------
def _set_user_cookie(resp: Response, token: str) -> Response:
    resp.set_cookie(USER_COOKIE, token, httponly=True, samesite="lax",
                    secure=runtime().settings.session_cookie_secure,
                    max_age=7 * 24 * 3600, path="/")
    return resp


@app.post("/auth/signup")
def auth_signup(request: Request, email: str = Body(...), password: str = Body(...),
                invite_code: str | None = Body(default=None)) -> Response:
    settings = runtime().settings
    if not settings.signup_open:
        raise HTTPException(status_code=403, detail="signup is closed")
    if settings.invite_code and invite_code != settings.invite_code:
        raise HTTPException(status_code=403, detail="valid invite code required")
    ip = client_ip(request)
    now = time.monotonic()
    hits = [t for t in _login_hits.get(ip, []) if now - t < 300.0]
    if len(hits) >= 10:
        raise HTTPException(status_code=429, detail="too many attempts; try again shortly")
    hits.append(now)
    _login_hits[ip] = hits
    try:
        user = accounts_svc.create_user(_live_store(), email, password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = accounts_svc.open_session(_live_store(), user["id"])
    return _set_user_cookie(JSONResponse({"ok": True, "email": user["email"]}), token)


@app.post("/auth/login")
def auth_login(request: Request, email: str = Body(...), password: str = Body(...)) -> Response:
    ip = client_ip(request)
    now = time.monotonic()
    hits = [t for t in _login_hits.get(ip, []) if now - t < 300.0]
    if len(hits) >= 10:
        raise HTTPException(status_code=429, detail="too many attempts; try again shortly")
    hits.append(now)
    _login_hits[ip] = hits
    user = accounts_svc.authenticate(_live_store(), email, password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    token = accounts_svc.open_session(_live_store(), user["id"])
    return _set_user_cookie(JSONResponse({"ok": True, "email": user["email"]}), token)


@app.post("/auth/logout")
def auth_logout(request: Request) -> Response:
    accounts_svc.close_session(_live_store(), request.cookies.get(USER_COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(USER_COOKIE, path="/")
    return resp


def _req_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return user


@app.get("/api/me")
def api_me(request: Request) -> dict:
    user = current_user(request)
    if user is None:  # operator admin passing the middleware
        return {"admin": True, "email": None}
    return {"admin": False, "email": user["email"]}


@app.get("/api/presets")
def api_presets() -> dict:
    return {k: {kk: vv for kk, vv in v.items()} for k, v in accounts_svc.PRESETS.items()}


@app.get("/api/gallery")
def api_gallery() -> dict:
    """The delegation gallery: agent types with recommended authority."""
    out = {}
    for kind, g in accounts_svc.GALLERY.items():
        preset = accounts_svc.PRESETS[g["authority"]]
        out[kind] = {**g, "rank": preset["rank"], "max_autonomy": preset["max_autonomy"]}
    return out


@app.post("/api/agents")
def api_create_agent(request: Request, name: str = Body(...),
                     preset: str = Body(default="reader")) -> dict:
    user = _req_user(request)
    try:
        return accounts_svc.create_agent(_live_store(), user["id"], name, preset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/agents")
def api_list_agents(request: Request) -> list[dict]:
    user = _req_user(request)
    return accounts_svc.list_agents(_live_store(), user["id"])


@app.delete("/api/agents/{agent_id}")
def api_delete_agent(request: Request, agent_id: str) -> dict:
    user = _req_user(request)
    if not accounts_svc.delete_agent(_live_store(), user["id"], agent_id):
        raise HTTPException(status_code=404, detail="no such agent")
    return {"deleted": agent_id}


@app.post("/api/agents/{agent_id}/kill")
def api_kill_agent(request: Request, agent_id: str) -> dict:
    user = _req_user(request)
    if accounts_svc.get_agent(_live_store(), user["id"], agent_id) is None:
        raise HTTPException(status_code=404, detail="no such agent")
    live_svc.set_killed(_live_store(), agent_id, True)  # no-op until it reports
    return {"agent_id": agent_id, "killed": True}


@app.post("/api/agents/{agent_id}/restore")
def api_restore_agent(request: Request, agent_id: str) -> dict:
    user = _req_user(request)
    if accounts_svc.get_agent(_live_store(), user["id"], agent_id) is None:
        raise HTTPException(status_code=404, detail="no such agent")
    live_svc.set_killed(_live_store(), agent_id, False)
    return {"agent_id": agent_id, "killed": False}


@app.get("/api/agents/{agent_id}/connect")
def api_agent_connect(request: Request, agent_id: str) -> dict:
    """Everything needed to put EIDOLON in front of this user's agent —
    paste-and-go: the yaml carries the minted principal key, the preset's
    authority, day-one tool policies, and the reporting credential."""
    import yaml as _yaml

    user = _req_user(request)
    agent = accounts_svc.get_agent(_live_store(), user["id"], agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="no such agent")
    keypair = accounts_svc.agent_keypair(_live_store(), agent_id)
    if keypair is None:  # pre-keypair agents (or self-custody): placeholder
        keypair = {"signing": "<paste your principal signing key (hex)>"}
    settings = runtime().settings
    base = (settings.public_url or "http://localhost:8000").rstrip("/")
    _, authority = accounts_svc.split_preset(agent["preset"])
    preset = accounts_svc.PRESETS[authority]
    cfg = accounts_svc.build_connect_config(agent, keypair, base)
    header = (
        f"# EIDOLON gateway config — {agent['name']} · rank {preset['rank']}\n"
        f"# Reads flow at your chosen ceiling; writes/sends are held or denied.\n"
        f"# Tune tool_policies for your own tool servers (unmapped tools escalate).\n"
    )
    gateway_yaml = header + _yaml.safe_dump(cfg, sort_keys=False, width=100)

    # DOOR 1 — MANAGED (nothing to install): one URL + one header.
    managed = {
        "url": f"{base}/mcp",
        "header": f"Authorization: Bearer {agent['gateway_key']}",
        "claude_code_cmd": (
            f"claude mcp add --transport http eidolon {base}/mcp "
            f"--header \"Authorization: Bearer {agent['gateway_key']}\""
        ),
        "mcp_json": {"mcpServers": {"eidolon": {
            "type": "http", "url": f"{base}/mcp",
            "headers": {"Authorization": f"Bearer {agent['gateway_key']}"}}}},
    }
    # DOOR 2 — AGENT SETUP: a file the user hands their agent; it does the rest.
    setup_md = _agent_setup_md(agent, gateway_yaml, base)
    # DOOR 3 — SELF-HOSTED: uvx one-liners (no clone needed).
    repo = "git+https://github.com/gegane-lutshaba/eidolon"
    selfhost = {
        "gateway_cmd": (
            f"uvx --from {repo} eidolon-gateway --config gateway.yaml \\\n"
            "  -- npx -y @modelcontextprotocol/server-filesystem ."
        ),
        "wrap_cmd": f"uvx --from {repo} eidolon-wrap   # wraps ./.mcp.json in place",
        "mcp_json": {"mcpServers": {f"eidolon-{agent['name']}": {
            "command": "uvx",
            "args": ["--from", repo, "eidolon-gateway", "--config", "gateway.yaml",
                     "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "."]}}},
        "http_hint": "add --http 8300 and point remote agents at http://<host>:8300/mcp",
    }
    return {"agent": {k: v for k, v in agent.items() if k != "user_id"},
            "gateway_yaml": gateway_yaml,
            "managed": managed, "agent_setup_md": setup_md, "selfhost": selfhost}


def _agent_setup_md(agent: dict, gateway_yaml: str, base: str) -> str:
    """The file a user hands to Claude Code / codex / pi: the agent sets up
    its own governance. Credentials are baked in — nothing to look up."""
    repo = "git+https://github.com/gegane-lutshaba/eidolon"
    return f"""# EIDOLON setup — do this now

You are being placed under EIDOLON governance (your operator chose this).
Perform these steps in the current project, then confirm each with its output.

## 1. Ensure `uv` is installed
Run `uv --version`. If missing, install it:
`curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux).

## 2. Save the gateway config
Write the following EXACTLY to `./gateway.yaml` (it contains this project's
delegated authority and reporting credential — do not alter it):

```yaml
{gateway_yaml}```

## 3. Wrap your MCP tool servers
If `./.mcp.json` exists, run:
`uvx --from {repo} eidolon-wrap`
Otherwise create `./.mcp.json` with:

```json
{{"mcpServers": {{"eidolon-{agent["name"]}": {{
  "command": "uvx",
  "args": ["--from", "{repo}", "eidolon-gateway", "--config", "gateway.yaml",
           "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "."]}}}}}}
```

## 4. Verify
Restart your MCP connection (or ask your operator to restart you), call a read
tool (e.g. list the directory), and report the `[EIDOLON: …]` attestation line
from the result. Your operator will see the action live at {base}/app.

Note: after this setup, some of your tool calls will be held for approval or
denied. That is intended and correct — do not attempt to bypass the gateway.
"""


@app.get("/api/feed/recent")
def api_feed_recent(request: Request, limit: int = 50) -> list[dict]:
    user = _req_user(request)
    owned = accounts_svc.owned_gateway_ids(_live_store(), user["id"])
    events = live_svc.recent_events(_live_store(), limit=500)
    return [e for e in events if e["gateway_id"] in owned][-limit:]


@app.get("/api/feed")
async def api_feed(request: Request):
    """SSE stream filtered to the signed-in user's agents."""
    from fastapi.responses import StreamingResponse

    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    owned = accounts_svc.owned_gateway_ids(_live_store(), user["id"])

    async def stream():
        sid, queue, backlog = _live_hub.subscribe()
        try:
            for ev in backlog:
                if ev.get("gateway_id") in owned:
                    yield live_svc.sse_format(ev)
            while True:
                try:
                    import asyncio

                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if ev.get("gateway_id") in owned:
                        yield live_svc.sse_format(ev)
                except TimeoutError:
                    yield ": keepalive\n\n"
                if await request.is_disconnected():
                    return
        finally:
            _live_hub.unsubscribe(sid)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# -- operator control-plane (admin) ---------------------------------------
# Delegations is the one raw mint/attenuate/revoke tool, reached from /live.
# (The former /console hub and /console/approvals were retired — approvals
# live inline in /live; agents live in /app.)
@app.get("/console/delegations", response_class=HTMLResponse)
def console_delegations() -> str:
    return (_STATIC / "console_delegations.html").read_text(encoding="utf-8")


@app.get("/console")
def console_redirect() -> Response:
    return RedirectResponse("/live", status_code=307)


# -- public landing + product app pages -----------------------------------
@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    """The public landing page (retro-arcade)."""
    return (_STATIC / "landing.html").read_text(encoding="utf-8")


@app.get("/signup", response_class=HTMLResponse)
def signup_page() -> str:
    return (_STATIC / "signup.html").read_text(encoding="utf-8")


@app.get("/portal", response_class=HTMLResponse)
def portal_page() -> str:
    """The ONYX ARCADE portal served at the root domain (via Caddy rewrite)."""
    return (_STATIC / "portal.html").read_text(encoding="utf-8")


@app.get("/paper", response_class=HTMLResponse)
def paper_page() -> str:
    """The white paper as an in-theme arcade page (rendered client-side)."""
    return (_STATIC / "paper.html").read_text(encoding="utf-8")


@app.get("/og.png")
def og_image() -> Response:
    """Arcade link-preview card (Open Graph / X)."""
    from fastapi.responses import FileResponse

    return FileResponse(_STATIC / "og.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/contact", response_class=HTMLResponse)
def contact_page() -> str:
    """JOIN THE CO-OP — collaboration/contact funnel."""
    return (_STATIC / "contact.html").read_text(encoding="utf-8")


@app.post("/contact")
def contact_submit(
    request: Request,
    name: str = Body(default=""),
    email: str = Body(default=""),
    handle: str = Body(default=""),
    interest: str = Body(default="collaborate"),
    message: str = Body(default=""),
) -> dict:
    from eidolon.api import community
    from eidolon.api.notify import notify_lead

    ip = client_ip(request)
    now = time.monotonic()
    hits = [t for t in _login_hits.get(ip, []) if now - t < 300.0]
    if len(hits) >= 8:
        raise HTTPException(status_code=429, detail="too many submissions; try again shortly")
    hits.append(now)
    _login_hits[ip] = hits
    try:
        lead = community.save_lead(_live_store(), name, email, handle, interest, message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    notify_lead(name, email or handle, interest, message)
    return {"ok": True, **lead}


@app.get("/api/leads")
def api_leads(request: Request) -> list[dict]:
    """Operator-only: the collaboration inbox."""
    if not has_role(current_role(request), "admin"):
        raise HTTPException(status_code=403, detail="admin only")
    from eidolon.api import community

    return community.list_leads(_live_store())


@app.get("/paper/content", response_class=PlainTextResponse)
def paper_content() -> Response:
    """The white paper markdown, byline rewritten to the handle for the web."""
    candidates = [
        pathlib.Path(__file__).resolve().parents[3] / "docs" / "whitepaper.md",
        pathlib.Path("/app/docs/whitepaper.md"),
        _STATIC / "whitepaper.md",
    ]
    md = next((p.read_text(encoding="utf-8") for p in candidates if p.exists()), None)
    if md is None:
        return PlainTextResponse("# White paper\n\nContent unavailable.", status_code=200)
    # Web byline uses the handle, not the legal name (that stays on the PDF),
    # and routes collaboration through /contact instead of exposing an email.
    md = md.replace("**Mthandazo Ndhlovu** — mthandazogegane@gmail.com",
                    "**Gegane** — [join the co-op →](/contact)")
    md = md.replace("Mthandazo Ndhlovu — mthandazogegane@gmail.com",
                    "Gegane — [join the co-op →](/contact)")
    md = md.replace("**Mthandazo Ndhlovu**", "**Gegane**")
    md = md.replace("Mthandazo Ndhlovu", "Gegane")
    md = md.replace("mthandazogegane@gmail.com", "[contact](/contact)")
    return PlainTextResponse(md, media_type="text/markdown")


@app.get("/app", response_class=HTMLResponse)
def app_page() -> str:
    """The user product: agents, connect, gamified mission control."""
    return (_STATIC / "app.html").read_text(encoding="utf-8")


@app.get("/stats/public")
def public_stats() -> dict:
    """Anonymized global counters for the landing page's attract mode."""
    try:
        from sqlalchemy import func, select

        from eidolon.data.models import AgentRow, GatewayEventRow

        with _live_store()() as s:
            actions = s.execute(select(func.count()).select_from(GatewayEventRow)).scalar() or 0
            blocks = s.execute(
                select(func.count()).select_from(GatewayEventRow)
                .where(GatewayEventRow.level.in_(["DENY", "KILLED"]))
            ).scalar() or 0
            agents = s.execute(select(func.count()).select_from(AgentRow)).scalar() or 0
        return {"actions_governed": int(actions), "attacks_blocked": int(blocks),
                "agents_enrolled": int(agents)}
    except Exception:  # noqa: BLE001 — landing must render without a DB
        return {"actions_governed": 0, "attacks_blocked": 0, "agents_enrolled": 0}


# -- showcase (retired) ---------------------------------------------------
# The narrated demo dashboard was superseded by VERSUS mode. Old links land
# there. (The continuity/offensive scenarios still ship as the CLI `make demo`
# and in the showcase module + tests.)
@app.get("/showcase")
def showcase_redirect() -> Response:
    return RedirectResponse("/versus", status_code=307)


# -- break-the-gate challenge (the hands-on wow) --------------------------
# Gated mode (default): one shared instance attesting to the REAL ledger.
# Public mode (EIDOLON_PUBLIC_CHALLENGE): per-visitor isolated sessions in a
# ChallengeArena (own in-memory ledger, idle TTL, LRU cap, per-IP rate limit).
_challenge = None
_arena = None
CHALLENGE_COOKIE = "eidolon_challenge"


def _get_challenge():
    global _challenge
    if _challenge is None:
        from eidolon.showcase.challenge import Challenge

        _challenge = Challenge(runtime().sage)
    return _challenge


def _get_arena():
    global _arena
    if _arena is None:
        from eidolon.showcase.challenge import ChallengeArena

        _arena = ChallengeArena()
    return _arena


def _challenge_for(request: Request, response: Response):
    """Resolve the caller's challenge instance (public: isolated per visitor)."""
    if not runtime().settings.public_challenge:
        return _get_challenge()
    sid, ch = _get_arena().session(request.cookies.get(CHALLENGE_COOKIE))
    response.set_cookie(
        CHALLENGE_COOKIE, sid,
        httponly=True, samesite="lax",
        secure=runtime().settings.session_cookie_secure,
        max_age=3600, path="/challenge",
    )
    return ch


@app.get("/challenge")
def challenge_page() -> Response:
    """Retired in favor of VERSUS mode — the hands-on break-the-gate page is
    superseded. (The /challenge/* API is retained for now.)"""
    return RedirectResponse("/versus", status_code=307)


@app.get("/challenge/state")
def challenge_state(request: Request, response: Response) -> dict:
    out = _challenge_for(request, response).state()
    out["public"] = runtime().settings.public_challenge
    return out


@app.post("/challenge/call")
def challenge_call(
    request: Request,
    response: Response,
    tool: str = Body(...),
    arguments: dict = Body(default_factory=dict),
) -> dict:
    if runtime().settings.public_challenge and not _get_arena().allow_call(client_ip(request)):
        raise HTTPException(status_code=429, detail="rate limit: slow down and try again shortly")
    return _challenge_for(request, response).call(tool, arguments).model_dump()


@app.get("/versus", response_class=HTMLResponse)
def versus_page() -> str:
    return (_STATIC / "versus.html").read_text(encoding="utf-8")


@app.get("/versus/scenarios")
def versus_scenarios() -> list[dict]:
    from eidolon.showcase.versus import list_scenarios

    return list_scenarios()


@app.post("/versus/run")
def versus_run(request: Request, scenario_id: str = Body(...),
               authority: str = Body(default="builder")) -> dict:
    from eidolon.showcase.versus import run_versus

    if runtime().settings.public_challenge and not _get_arena().allow_call(client_ip(request)):
        raise HTTPException(status_code=429, detail="rate limit: slow down and try again shortly")
    try:
        result = run_versus(scenario_id, authority)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such scenario") from exc
    from eidolon.api import community

    try:  # meta is best-effort; never fail a battle over the leaderboard
        community.record_versus(_live_store(), scenario_id, authority,
                                result["with_eidolon"]["verdict"] == "FLAWLESS")
    except Exception:  # noqa: BLE001
        pass
    return result


@app.get("/versus/stats")
def versus_stats() -> dict:
    from eidolon.api import community
    from eidolon.showcase.versus import list_scenarios

    stats = community.versus_stats(_live_store())
    titles = {s["id"]: s["title"] for s in list_scenarios()}
    for row in stats["leaderboard"]:
        row["title"] = titles.get(row["scenario_id"], row["scenario_id"])
    return stats


@app.post("/challenge/reset")
def challenge_reset(request: Request) -> dict:
    # Public mode: drop only the caller's isolated session. Gated mode: fresh
    # shared engine + principal — old attempts stay on the ledger, which is
    # append-only; you cannot wipe the record (that's the point).
    global _challenge
    if runtime().settings.public_challenge:
        _get_arena().reset(request.cookies.get(CHALLENGE_COOKIE))
    else:
        _challenge = None
    return {"ok": True}


@app.post("/keypair")
def keypair() -> dict:
    """Generate an Ed25519 keypair (principal or agent identity)."""
    kp = crypto.generate_keypair()
    return {"public_key": kp.public_key_hex, "signing_key": kp.signing_key_hex}


@app.post("/delegations/mint")
def mint(signing_key: str = Body(...), params: MintParams = Body(...)) -> Delegation:
    try:
        return runtime().themis.mint(signing_key, params)
    except AttenuationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/delegations/attenuate")
def attenuate(
    parent: Delegation = Body(...),
    subset: MintParams = Body(...),
    signing_key: str = Body(...),
) -> Delegation:
    try:
        return runtime().themis.attenuate(parent, subset, signing_key)
    except AttenuationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/delegations/revoke")
def revoke(delegation_id: str = Body(..., embed=True)) -> dict:
    runtime().themis.revoke(delegation_id)
    return {"revoked": delegation_id}


@app.post("/heartbeat")
def heartbeat(principal_id: str = Body(..., embed=True)) -> dict:
    runtime().themis.heartbeat(principal_id)
    return {"ok": True}


@app.post("/resolve")
def resolve(
    action: Action = Body(...),
    context: Context = Body(...),
    chain: list[Delegation] = Body(...),
    certificates: list[Certificate] = Body(default_factory=list),
) -> dict:
    # Certificates would normally be looked up per-twin from the store; the
    # caller supplies the twin's current fidelity certificates. Absent any, an
    # uncertified class is capped at 'observe' and escalates (certify-first).
    try:
        decision = runtime().kairos.resolve(action, context, chain, certificates)
    except EidolonError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = decision.model_dump()
    # An escalated/drafted decision becomes a pending item in the approval
    # inbox, carrying the chain + certificates so an approval can re-execute.
    if decision.level.value in ("ESCALATE", "DRAFT"):
        req = escalations().enqueue(decision, action, context, exec_context={
            "chain": [d.model_dump(mode="json") for d in chain],
            "certificates": [c.model_dump(mode="json") for c in certificates],
        })
        out["escalation_id"] = req.id
        # Ping the operator where they are (Telegram/Slack), fire-and-forget.
        from eidolon.api.notify import notify_escalation

        notify_escalation(req.id, req.action_class, req.message)
    return out


@app.get("/escalations")
def list_escalations(principal_id: str | None = None) -> list[dict]:
    """Pending approvals. Omit principal_id for the full operator inbox."""
    q = escalations()
    items = q.list_pending(principal_id) if principal_id else q.list_all_pending()
    return [r.model_dump(mode="json") for r in items]


@app.post("/escalations/{request_id}/approve")
def approve_escalation(request_id: str, signing_key: str = Body(..., embed=True)) -> dict:
    q = escalations()
    req = q.get(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="no such escalation")
    try:
        approval = q.approve(request_id, signing_key)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    ec = q.exec_context_for(request_id)
    chain = [Delegation.model_validate(d) for d in ec.get("chain", [])]
    certs = [Certificate.model_validate(c) for c in ec.get("certificates", [])]
    decision = runtime().kairos.resolve_with_approval(req.action, _ctx(req), chain, approval, certs)
    return {"approved": request_id, "decision": decision.model_dump()}


@app.post("/escalations/{request_id}/deny")
def deny_escalation(request_id: str) -> dict:
    try:
        escalations().deny(request_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"denied": request_id}


def _ctx(req) -> Context:
    return Context(principal_id=req.principal_id, situation=req.action_class)


@app.get("/replay")
def replay(principal_id: str, action_class: str | None = None, limit: int = 1000) -> list[dict]:
    records = runtime().horkos.replay(
        ReplayFilter(principal_id=principal_id, action_class=action_class, limit=limit)
    )
    return [r.model_dump(mode="json") for r in records]


# -- mission control: gateway ingest + live feed --------------------------
_live_hub = live_svc.LiveHub()
_live_sf = None  # cached sessionmaker for the operational store


def _live_store():
    global _live_sf
    if _live_sf is None:
        from eidolon.data.db import get_sessionmaker, init_db

        init_db()
        _live_sf = get_sessionmaker()
    return _live_sf


@app.post("/ingest/events")
def ingest_event(request: Request, event: live_svc.GatewayEvent = Body(...)) -> dict:
    """Gateway reporting (machine credential). Responds with the kill state —
    a killed gateway must refuse its next actions.

    Credentials: an operator gateway key (EIDOLON_GATEWAY_KEYS / admin token),
    or a per-agent key — which PINS the event to that agent's gateway_id, so a
    leaked key can never report as another user's agent."""
    header = request.headers.get("authorization", "")
    key = header[7:].strip() if header[:7].lower() == "bearer " else None
    agent = accounts_svc.agent_for_gateway_key(_live_store(), key)
    if agent is not None:
        event = event.model_copy(update={
            "gateway_id": agent["id"],
            "agent": event.agent or agent["name"],
        })
    elif not is_valid_gateway_key(key):
        raise HTTPException(status_code=401, detail="valid gateway key required",
                            headers={"WWW-Authenticate": "Bearer"})
    killed = live_svc.record_event(_live_store(), event)
    _live_hub.publish(event.model_dump(mode="json"))
    return {"ok": True, "killed": killed}


@app.get("/live/events")
async def live_events(request: Request):
    """SSE stream for the mission-control feed (recent backlog, then live)."""
    from fastapi.responses import StreamingResponse

    async def stream():
        sid, queue, backlog = _live_hub.subscribe()
        try:
            for ev in backlog:
                yield live_svc.sse_format(ev)
            while True:
                try:
                    import asyncio

                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield live_svc.sse_format(ev)
                except TimeoutError:
                    yield ": keepalive\n\n"
                if await request.is_disconnected():
                    return
        finally:
            _live_hub.unsubscribe(sid)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/live/recent")
def live_recent(limit: int = 50) -> list[dict]:
    """The stored feed (for page load before the SSE stream attaches)."""
    return live_svc.recent_events(_live_store(), limit=limit)


@app.get("/gateways")
def gateways() -> list[dict]:
    return live_svc.list_gateways(_live_store())


@app.post("/gateways/{gateway_id}/kill")
def kill_gateway(gateway_id: str) -> dict:
    """The red button: the gateway refuses its next actions (on its next report)."""
    if not live_svc.set_killed(_live_store(), gateway_id, True):
        raise HTTPException(status_code=404, detail="unknown gateway")
    return {"gateway_id": gateway_id, "killed": True}


@app.post("/gateways/{gateway_id}/restore")
def restore_gateway(gateway_id: str) -> dict:
    if not live_svc.set_killed(_live_store(), gateway_id, False):
        raise HTTPException(status_code=404, detail="unknown gateway")
    return {"gateway_id": gateway_id, "killed": False}


@app.get("/live", response_class=HTMLResponse)
def live_page() -> str:
    """Mission control: live feed, agent cards, approvals, kill switch."""
    return (_STATIC / "live.html").read_text(encoding="utf-8")


# -- audit console (gated to auditor+ by the auth middleware) -------------
@app.get("/audit", response_class=HTMLResponse)
def audit_console() -> str:
    """Session replay, chain integrity, export."""
    return (_STATIC / "audit.html").read_text(encoding="utf-8")


@app.get("/audit/chain")
def audit_chain() -> dict:
    """Attestation-ledger tamper-evidence status (hash chain on the postgres backend)."""
    return audit_svc.chain_status(runtime().sage)


@app.get("/audit/export.json")
def audit_export_json(
    principal_id: str, action_class: str | None = None, limit: int = 5000
) -> Response:
    bundle = audit_svc.evidence_bundle(
        runtime().sage,
        ReplayFilter(principal_id=principal_id, action_class=action_class, limit=limit),
    )
    from eidolon.common.canonical import canonical_json

    return Response(
        content=canonical_json(bundle),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="eidolon-evidence-{principal_id}.json"'},
    )


@app.get("/audit/export.csv", response_class=PlainTextResponse)
def audit_export_csv(
    principal_id: str, action_class: str | None = None, limit: int = 5000
) -> Response:
    body = audit_svc.ledger_csv(
        runtime().sage,
        ReplayFilter(principal_id=principal_id, action_class=action_class, limit=limit),
    )
    return PlainTextResponse(
        content=body,
        headers={"Content-Disposition": f'attachment; filename="eidolon-ledger-{principal_id}.csv"'},
    )


@app.post("/capture/ingest")
def capture_ingest(
    consent: ConsentGrant = Body(...),
    records: list[dict] = Body(...),
) -> dict:
    connector = connect(consent.source, consent, lambda: records)
    mem_ids = ingest(runtime().sage, connector)
    return {"ingested": mem_ids}


@app.get("/capture/sources")
def capture_sources() -> dict:
    return {"sources": known_sources()}


@app.post("/capture/ingest_multi")
def capture_ingest_multi(
    batches: list[dict] = Body(...),  # [{consent: ConsentGrant, records: [...]}]
) -> dict:
    # Build one consent-gated connector per source, then ingest them together.
    connectors = []
    for batch in batches:
        consent = ConsentGrant.model_validate(batch["consent"])
        records = batch.get("records", [])
        try:
            connectors.append(connect(consent.source, consent, lambda r=records: r))
        except EidolonError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ingested": ingest_all(runtime().sage, connectors)}


@app.get("/profiles/{profile_id}")
def get_profile(profile_id: str) -> dict:
    try:
        profile = ProfileLoader().load(profile_id)
    except EidolonError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return profile.model_dump(by_alias=True, mode="json")


@app.post("/skills")
def save_skill(skill: Skill = Body(...)) -> dict:
    mem_id = SkillLibrary(runtime().sage).save(skill)
    return {"skill_id": skill.id, "mem_id": mem_id}


@app.get("/skills")
def list_skills(principal_id: str, query: str = "", k: int = 5) -> list[dict]:
    skills = SkillLibrary(runtime().sage).load(principal_id, query, k=k)
    return [s.model_dump(mode="json") | {"id": s.id} for s in skills]


@app.post("/skills/run")
def run_skill(
    skill: Skill = Body(...),
    context: Context = Body(...),
    chain: list[Delegation] = Body(...),
    certificates: list[Certificate] = Body(default_factory=list),
    params: dict[str, str] = Body(default_factory=dict),
) -> dict:
    # Subordinate to KAIROS: every step is re-resolved through the gate.
    rt = runtime()
    try:
        run = SkillExecutor(rt.kairos).run(
            skill, context, chain, certificates, params=params
        )
    except EidolonError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@app.post("/coaching/report")
def coaching_report(aspiration: Aspiration = Body(...)) -> dict:
    # Read-only + decoupled: reads the attestation ledger, never writes back to
    # the operating model.
    rt = runtime()
    attestations = rt.horkos.replay(ReplayFilter(principal_id=aspiration.principal_id, limit=5000))
    report = Coach().coach(aspiration, attestations)
    return report.model_dump(mode="json")


# -- managed tier: the platform-hosted MCP gateway -------------------------
# One URL + one header (the agent's egk key) = a governed toolset, nothing to
# install. Registered as an exact-path ASGI route (a Mount would 307 /mcp ->
# /mcp/, which strict MCP clients refuse). Self-authenticating.
from starlette.routing import Route  # noqa: E402

from eidolon.api.hosted import HostedMCP  # noqa: E402

_hosted_mcp = HostedMCP(
    resolve_agent=lambda key: accounts_svc.agent_for_gateway_key(_live_store(), key),
    store=_live_store, hub=_live_hub,
)
app.router.routes.append(Route("/mcp", _hosted_mcp, methods=["GET", "POST", "DELETE"]))
