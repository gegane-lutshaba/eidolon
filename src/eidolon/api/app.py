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

from eidolon.api import audit as audit_svc
from eidolon.api.auth import (
    SESSION_COOKIE,
    auth_enabled,
    current_role,
    has_role,
    required_role,
    role_for_token,
)
from eidolon.basanos.certify import Certificate
from eidolon.capture import ConsentGrant, connect, ingest, ingest_all, known_sources
from eidolon.coaching import Aspiration, Coach
from eidolon.common import crypto
from eidolon.common.errors import AttenuationError, EidolonError
from eidolon.config import Settings
from eidolon.escalation import EscalationQueue
from eidolon.ethos.style import ClaudeStyleEngine
from eidolon.profile import ProfileLoader
from eidolon.runtime import Runtime, build_runtime
from eidolon.sage.port import ReplayFilter
from eidolon.showcase import continuity_scenario, offensive_scenario
from eidolon.skills import Skill, SkillExecutor, SkillLibrary
from eidolon.themis.types import Delegation, MintParams
from eidolon.types import Action, Context

app = FastAPI(title="EIDOLON", version="0.1.0")

_STATIC = pathlib.Path(__file__).parent / "static"

_runtime: Runtime | None = None
_escalations = EscalationQueue()
_login_hits: dict[str, list[float]] = {}  # ip -> recent login attempt times


def runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = build_runtime()
    return _runtime


@app.middleware("http")
async def _gate_and_harden(request: Request, call_next):
    """Central auth gate (path/method policy) + baseline security headers."""
    needed = required_role(request.method, request.url.path)
    if needed is not None:
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
    ip = request.client.host if request.client else "?"
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
    return {"role": current_role(request), "auth_enabled": auth_enabled()}


# -- operator control-plane console (admin) -------------------------------
@app.get("/console", response_class=HTMLResponse)
def console_home() -> str:
    return (_STATIC / "console.html").read_text(encoding="utf-8")


@app.get("/console/delegations", response_class=HTMLResponse)
def console_delegations() -> str:
    return (_STATIC / "console_delegations.html").read_text(encoding="utf-8")


@app.get("/console/approvals", response_class=HTMLResponse)
def console_approvals() -> str:
    return (_STATIC / "console_approvals.html").read_text(encoding="utf-8")


# -- showcase dashboard ---------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """The showcase dashboard — runs live scenarios against the real core."""
    return (_STATIC / "dashboard.html").read_text(encoding="utf-8")


@app.post("/demo/continuity")
def demo_continuity(voice: bool = False) -> dict:
    # voice=1 renders drafts/escalations with Claude (needs an API key); the
    # decision path never depends on it.
    style = ClaudeStyleEngine(Settings()) if voice else None
    return continuity_scenario(style=style).model_dump(mode="json")


@app.post("/demo/offensive")
def demo_offensive() -> dict:
    return offensive_scenario().model_dump(mode="json")


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
    # An escalated/drafted decision becomes a pending item in the approval inbox.
    if decision.level.value in ("ESCALATE", "DRAFT"):
        req = _escalations.enqueue(decision, action, context)
        _esc_context[req.id] = (chain, certificates)
        out["escalation_id"] = req.id
    return out


# request_id -> (chain, certificates) so an approval can re-execute the action.
_esc_context: dict[str, tuple] = {}


@app.get("/escalations")
def list_escalations(principal_id: str | None = None) -> list[dict]:
    """Pending approvals. Omit principal_id for the full operator inbox."""
    items = (
        _escalations.list_pending(principal_id)
        if principal_id
        else _escalations.list_all_pending()
    )
    return [r.model_dump(mode="json") for r in items]


@app.post("/escalations/{request_id}/approve")
def approve_escalation(request_id: str, signing_key: str = Body(..., embed=True)) -> dict:
    req = _escalations.get(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="no such escalation")
    try:
        approval = _escalations.approve(request_id, signing_key)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    chain, certs = _esc_context.get(request_id, ([], []))
    decision = runtime().kairos.resolve_with_approval(req.action, _ctx(req), chain, approval, certs)
    return {"approved": request_id, "decision": decision.model_dump()}


@app.post("/escalations/{request_id}/deny")
def deny_escalation(request_id: str) -> dict:
    try:
        _escalations.deny(request_id)
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
