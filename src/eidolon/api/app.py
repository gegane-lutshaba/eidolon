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

from fastapi import Body, FastAPI, HTTPException

from eidolon.basanos.certify import Certificate
from eidolon.capture import ConsentGrant, connect, ingest, ingest_all, known_sources
from eidolon.coaching import Aspiration, Coach
from eidolon.common import crypto
from eidolon.common.errors import AttenuationError, EidolonError
from eidolon.profile import ProfileLoader
from eidolon.runtime import Runtime, build_runtime
from eidolon.sage.port import ReplayFilter
from eidolon.skills import Skill, SkillExecutor, SkillLibrary
from eidolon.themis.types import Delegation, MintParams
from eidolon.types import Action, Context

app = FastAPI(title="EIDOLON", version="0.1.0")

_runtime: Runtime | None = None


def runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = build_runtime()
    return _runtime


@app.get("/health")
def health() -> dict:
    rt = runtime()
    return {
        "status": "ok",
        "sage_backend": rt.settings.sage_backend,
        "profile": f"{rt.profile.id}@{rt.profile.version}",
    }


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
    return decision.model_dump()


@app.get("/replay")
def replay(principal_id: str, action_class: str | None = None, limit: int = 1000) -> list[dict]:
    records = runtime().horkos.replay(
        ReplayFilter(principal_id=principal_id, action_class=action_class, limit=limit)
    )
    return [r.model_dump(mode="json") for r in records]


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
