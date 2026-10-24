"""The gate's seam API (PRD §6): one HTTP endpoint per component interface.

    POST /delegations/mint|attenuate|register|revoke -> THEMIS
    POST /heartbeat                                  -> THEMIS dead-man's switch
    POST /resolve                                    -> KAIROS (the gate)
    POST /certify                                    -> BASANOS (earned certificates)
    GET/POST /escalations/...                        -> approval inbox
    GET  /replay                                     -> HORKOS
    POST /capture/...                                -> capture
    GET  /profiles/{id}                              -> ProfileLoader
    POST /skills, /skills/run                        -> skills (subordinate to KAIROS)
    POST /coaching/report                            -> coaching (read-only)

Auth is applied centrally by the app middleware (``auth.required_role``). Shared
state (the runtime, the escalation inbox) lives in ``eidolon.api.app`` and is
reached at call time, so tests and the app reset it in one place.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from eidolon.basanos.certify import Certificate, HeldoutDecision
from eidolon.capture import ConsentGrant, connect, ingest, ingest_all, known_sources
from eidolon.coaching import Aspiration, Coach
from eidolon.common import crypto
from eidolon.common.errors import AttenuationError, EidolonError
from eidolon.escalation.types import Approval
from eidolon.profile import ProfileLoader
from eidolon.sage.port import ReplayFilter
from eidolon.skills import Skill, SkillExecutor, SkillLibrary
from eidolon.themis.types import Delegation, MintParams
from eidolon.types import Action, Context

router = APIRouter()


def _core():
    from eidolon.api import app

    return app


def runtime():
    return _core().runtime()


def escalations():
    return _core().escalations()


def _require_server_signing() -> None:
    """Endpoints that move a private key over HTTP are a convenience for dev and
    demos. With EIDOLON_ALLOW_SERVER_SIGNING=false they are refused; sign
    client-side and use the pre-signed variants instead."""
    if not runtime().settings.allow_server_signing:
        raise HTTPException(
            status_code=403,
            detail="server-side signing is disabled (EIDOLON_ALLOW_SERVER_SIGNING=false): "
                   "sign locally and use /delegations/register or a pre-signed approval")


@router.post("/keypair")
def keypair() -> dict:
    """Generate an Ed25519 keypair (dev convenience — the key crosses HTTP)."""
    _require_server_signing()
    kp = crypto.generate_keypair()
    return {"public_key": kp.public_key_hex, "signing_key": kp.signing_key_hex}


@router.post("/delegations/mint")
def mint(signing_key: str = Body(...), params: MintParams = Body(...)) -> Delegation:
    _require_server_signing()
    try:
        return runtime().themis.mint(signing_key, params)
    except AttenuationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/delegations/attenuate")
def attenuate(
    parent: Delegation = Body(...),
    subset: MintParams = Body(...),
    signing_key: str = Body(...),
) -> Delegation:
    _require_server_signing()
    try:
        return runtime().themis.attenuate(parent, subset, signing_key)
    except AttenuationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/delegations/register")
def register_delegation(chain: list[Delegation] = Body(..., embed=True)) -> dict:
    """Register a chain signed client-side (``Themis.mint`` / ``attenuate`` run
    locally, so no private key reaches the server). Verifies every signature and
    link and arms the root principal's dead-man's switch, as server mint does."""
    rt = runtime()
    result = rt.themis.verify(None, chain)
    if not result.valid:
        raise HTTPException(status_code=400, detail=f"invalid delegation chain: {result.reason}")
    root = next(d for d in chain if d.body.parent is None)
    rt.themis.heartbeat(root.body.principal_id)
    return {"registered": [d.id for d in chain], "principal_id": root.body.principal_id}


@router.post("/delegations/revoke")
def revoke(delegation_id: str = Body(..., embed=True)) -> dict:
    runtime().themis.revoke(delegation_id)
    return {"revoked": delegation_id}


@router.post("/heartbeat")
def heartbeat(principal_id: str = Body(..., embed=True)) -> dict:
    runtime().themis.heartbeat(principal_id)
    return {"ok": True}


@router.post("/resolve")
def resolve(
    action: Action = Body(...),
    context: Context = Body(...),
    chain: list[Delegation] = Body(...),
    certificates: list[Certificate] = Body(default_factory=list),
) -> dict:
    # Certificates are earned, never asserted: the gate uses the ones this
    # server issued (POST /certify) plus presented ones with a valid issuer
    # signature for this principal. Anything else is dropped and reported; an
    # uncertified class is capped at 'observe' and escalates (certify-first).
    rt = runtime()
    certificates, rejected = rt.certificates_for(context.principal_id, certificates)
    try:
        decision = rt.kairos.resolve(action, context, chain, certificates)
    except EidolonError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = decision.model_dump()
    if rejected:
        out["certificates_rejected"] = rejected
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


@router.post("/certify")
def certify(principal_id: str = Body(...),
            heldout_decisions: list[HeldoutDecision] = Body(...)) -> dict:
    """Run BASANOS fidelity certification server-side against the principal's
    held-out real decisions. The resulting certificates are signed, stored for
    the principal, and returned (presentable to /resolve, bound to this
    principal). This is the only way the API raises an autonomy ceiling."""
    rt = runtime()

    def twin(action: Action, context: Context):
        memories = rt.sage.recall(context.principal_id, action.scope,
                                  context.query or action.description, 8)
        return rt.ethos.evaluate(action, context, memories, rt.profile)

    certs = rt.basanos.certify_fidelity(twin, heldout_decisions, rt.profile)
    signed = [rt.issuer.sign(c, principal_id) for c in certs]
    rt.issued.setdefault(principal_id, {}).update({c.action_class: c for c in signed})
    return {"principal_id": principal_id,
            "certificates": [c.model_dump(mode="json") for c in signed]}


@router.get("/escalations")
def list_escalations(principal_id: str | None = None) -> list[dict]:
    """Pending approvals. Omit principal_id for the full operator inbox."""
    q = escalations()
    items = q.list_pending(principal_id) if principal_id else q.list_all_pending()
    return [r.model_dump(mode="json") for r in items]


@router.get("/escalations/{request_id}")
def get_escalation(request_id: str) -> dict:
    """One escalation, plus the ``action_digest`` a principal signs to approve it
    client-side (``escalation.make_approval`` with the principal's local key)."""
    from eidolon.escalation.types import action_digest

    req = escalations().get(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="no such escalation")
    out = req.model_dump(mode="json")
    out["action_digest"] = action_digest(req.action, req.principal_id)
    return out


@router.post("/escalations/{request_id}/approve")
def approve_escalation(request_id: str, signing_key: str | None = Body(default=None),
                       approval: Approval | None = Body(default=None)) -> dict:
    """Approve with a pre-signed ``approval`` (preferred: the key never leaves the
    principal), or — dev convenience — with the raw ``signing_key``."""
    q = escalations()
    req = q.get(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="no such escalation")
    if approval is None and signing_key is None:
        raise HTTPException(status_code=422, detail="provide a signed `approval` (or `signing_key`)")
    try:
        if approval is not None:
            approval = q.approve_signed(request_id, approval)
        else:
            _require_server_signing()
            assert signing_key is not None  # checked above
            approval = q.approve(request_id, signing_key)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    ec = q.exec_context_for(request_id)
    chain = [Delegation.model_validate(d) for d in ec.get("chain", [])]
    certs = [Certificate.model_validate(c) for c in ec.get("certificates", [])]
    decision = runtime().kairos.resolve_with_approval(req.action, _ctx(req), chain, approval, certs)
    return {"approved": request_id, "decision": decision.model_dump()}


@router.post("/escalations/{request_id}/deny")
def deny_escalation(request_id: str) -> dict:
    try:
        escalations().deny(request_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"denied": request_id}


def _ctx(req) -> Context:
    return Context(principal_id=req.principal_id, situation=req.action_class)


@router.get("/replay")
def replay(principal_id: str, action_class: str | None = None, limit: int = 1000) -> list[dict]:
    records = runtime().horkos.replay(
        ReplayFilter(principal_id=principal_id, action_class=action_class, limit=limit)
    )
    return [r.model_dump(mode="json") for r in records]



@router.post("/capture/ingest")
def capture_ingest(
    consent: ConsentGrant = Body(...),
    records: list[dict] = Body(...),
) -> dict:
    connector = connect(consent.source, consent, lambda: records)
    mem_ids = ingest(runtime().sage, connector)
    return {"ingested": mem_ids}


@router.get("/capture/sources")
def capture_sources() -> dict:
    return {"sources": known_sources()}


@router.post("/capture/ingest_multi")
def capture_ingest_multi(
    batches: list[dict] = Body(...),  # [{consent: ConsentGrant, records: [...]}]
) -> dict:
    # Build one consent-gated connector per source, then ingest them together.
    connectors: list = []
    for batch in batches:
        consent = ConsentGrant.model_validate(batch["consent"])
        records = batch.get("records", [])
        try:
            connectors.append(connect(consent.source, consent, lambda r=records: r))
        except EidolonError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ingested": ingest_all(runtime().sage, connectors)}


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str) -> dict:
    try:
        profile = ProfileLoader().load(profile_id)
    except EidolonError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return profile.model_dump(by_alias=True, mode="json")


@router.post("/skills")
def save_skill(skill: Skill = Body(...)) -> dict:
    mem_id = SkillLibrary(runtime().sage).save(skill)
    return {"skill_id": skill.id, "mem_id": mem_id}


@router.get("/skills")
def list_skills(principal_id: str, query: str = "", k: int = 5) -> list[dict]:
    skills = SkillLibrary(runtime().sage).load(principal_id, query, k=k)
    return [s.model_dump(mode="json") | {"id": s.id} for s in skills]


@router.post("/skills/run")
def run_skill(
    skill: Skill = Body(...),
    context: Context = Body(...),
    chain: list[Delegation] = Body(...),
    certificates: list[Certificate] = Body(default_factory=list),
    params: dict[str, str] = Body(default_factory=dict),
) -> dict:
    # Subordinate to KAIROS: every step is re-resolved through the gate.
    rt = runtime()
    certificates, _rejected = rt.certificates_for(context.principal_id, certificates)
    try:
        run = SkillExecutor(rt.kairos).run(
            skill, context, chain, certificates, params=params
        )
    except EidolonError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@router.post("/coaching/report")
def coaching_report(aspiration: Aspiration = Body(...)) -> dict:
    # Read-only + decoupled: reads the attestation ledger, never writes back to
    # the operating model.
    rt = runtime()
    attestations = rt.horkos.replay(ReplayFilter(principal_id=aspiration.principal_id, limit=5000))
    report = Coach().coach(aspiration, attestations)
    return report.model_dump(mode="json")
