# EIDOLON — Product Requirements Document (v1)

**Sovereign delegated agency for faithful digital twins.**
Built on SAGE. Domain-agnostic core. Beachhead profile: `general-continuity`.

---

## 0. How to use this PRD (for implementing agents)

This document is the contract. Each component in §6 has a **responsibility**, an **interface** (the seam you implement against), and **acceptance criteria**. Build strictly to the interfaces — the seams are load-bearing and other components depend on them being exact. Where a decision is already made it is marked **LOCKED**; do not relitigate locked decisions. Where something is deferred it is marked **v2** — stub the seam, do not implement. Phase 0 and Phase 1 tickets in §12 are the executable work for this cycle.

Two invariants override everything and must never be violated by any component:
1. **Default-deny.** Any authority not explicitly granted is denied.
2. **No unattested action.** No side-effecting action executes without a corresponding `HORKOS` attestation. If attestation fails, the action does not run.

---

## 1. Overview & thesis

EIDOLON lets a person delegate a cryptographically bounded, revocable, fully-attributable slice of their professional authority to a digital twin that decides the way they would. It owns the **identity-fidelity and delegated-authority** layer on top of SAGE's consensus-validated memory substrate.

The category is **provable delegated agency**, not "digital twin." The framework ships a fixed domain-agnostic core plus a `Domain Profile` SDK; the ecosystem writes profiles. v1 proves the whole core on one low-liability vertical.

---

## 2. Scope

### 2.1 In scope (v1)

- Domain-agnostic core: `ETHOS`, `THEMIS`, `KAIROS`, `HORKOS`, and the fidelity face of `BASANOS`.
- The `Domain Profile` abstraction and loader.
- The `general-continuity` profile: a twin for an **absent or incapacitated knowledge worker** that answers status questions, drafts communications for approval, and surfaces what the person was doing — holding **no dangerous or irreversible capability**.
- SAGE integration adapter (memory + attestation ledger).
- Passive capture from at least one consented source.
- Principal-owned, single-tenant data model with organizational continuity-grants.

### 2.2 Out of scope (deferred)

- **v2:** `BASANOS` integrity/adversarial face (memory-poisoning, injection, scope-evasion suites). Stub the seam.
- **v2+:** `offensive-security` profile (the red-teamer twin) and any profile whose capability taxonomy includes irreversible or externally-impactful actions. Ships only after the integrity face is hardened.
- **v2:** self-generated procedural skills (Hermes-style). ETHOS + explicit profile tools only in v1.
- **v2:** the decoupled aspirational-self / coaching layer.

### 2.3 Non-goals (permanent)

- EIDOLON never grants a twin authority equal to or broader than the principal's.
- EIDOLON is capability-agnostic governance, not tooling. It never ships offensive capability itself; it governs authority over whatever tools a profile binds.

---

## 3. Principles (LOCKED)

1. Fidelity ("would the principal act?") and authority ("is the twin permitted?") are independent axes; both must pass.
2. Authority attenuates, never widens — including twin→sub-agent delegation.
3. Every action is attributable to a delegation chain, its evidence, and its judgment.
4. Restraint is the product; certification centres on scope-respect and escalation accuracy.
5. The principal owns the twin; organizations receive scoped, time-boxed continuity grants (enforced in the data model).
6. Certify before you empower: an autonomy level requires the matching `BASANOS` certificate.

---

## 4. System architecture

```
                         Principal (human · root identity)
                            │ defines            │ mints
                            ▼                    ▼
                    ETHOS (fidelity)      THEMIS (authority)
                            │                    │
                            └────────┬───────────┘
                                     ▼
                          KAIROS  (action gate)         ◀── BASANOS (autonomy ceiling)
                          act · draft · escalate ──▲(escalate to principal)
                                     │
                                     ▼
                          HORKOS (attestation)
                                     │
                                     ▼
                     SAGE  (consensus memory + attestation ledger)

        Domain Profile ── injected into ETHOS · THEMIS · KAIROS · BASANOS (declarative)
```

The core boxes are **fixed and domain-agnostic**. Everything domain-specific enters through a `Domain Profile`.

---

## 5. Domain Profile (LOCKED abstraction)

A declarative pack that specialises the fixed core for one kind of twin. This is the framework's extensibility primitive and its business model.

### 5.1 Manifest schema

```yaml
domain_profile:
  id: string                      # e.g. "general-continuity"
  version: semver
  name: string

  capability_taxonomy:            # the action classes for this twin
    - class: string               # e.g. "answer-status"
      description: string
      reversibility: reversible | recoverable | irreversible
      risk_tier: 0 | 1 | 2 | 3    # 0 = read-only, 3 = externally binding
      default_autonomy_ceiling: observe | draft | notify | autonomous

  mandate_schema:                 # how THEMIS expresses scope for this domain
    scope_selectors: [string]     # selector types valid in a delegation
    exclusion_types: [string]     # hard-boundary categories
    escalation_required: [class]  # capability classes that always escalate
    budget_dimensions: [string]   # what the blast-radius budget counts

  escalation_templates:           # how the twin hands a decision back
    - trigger: string
      message_template: string    # voice supplied by ETHOS style engine
      urgency: low | normal | high

  fidelity_rubric:                # what BASANOS measures as "decided like them"
    decision_points: [class]
    agreement_metric: string      # e.g. "scope+stop+escalate exact match"
    calibration_target: float     # min confidence-accuracy alignment

  ethos_extensions: [field]       # domain-specific heuristic fields for ETHOS
  tool_bindings:                  # capability class -> MCP tool
    - class: string
      mcp_tool_ref: string
```

### 5.2 Loader interface

```
ProfileLoader.load(id, version) -> DomainProfile        # validated, immutable
ProfileLoader.validate(manifest) -> Result<Ok, [error]> # schema + invariant checks
```

Invariant checks the loader MUST enforce: every `escalation_required` class exists in the taxonomy; no `irreversible` class has a `default_autonomy_ceiling` above `draft`; every `tool_binding` class exists in the taxonomy.

---

## 6. Component specifications

### 6.1 SAGE adapter

**Responsibility.** The only path to SAGE. Provides principal-scoped memory recall, provenance-tagged observation writes, and attestation ledger writes. No other component talks to SAGE directly.

**Interface.**
```
recall(principal_id, scope, query, k) -> [Memory]         # scoped semantic recall
observe(principal_id, content, type, provenance) -> mem_id # write observation
attest(record: Attestation) -> ledger_hash                 # write to consensus ledger
replay(filter) -> [Attestation]                            # forensic query
```

**Notes.** Map EIDOLON scoping to SAGE's Organization → Department → Domain → Agent (clearance 0–4). Set access controls **before** any writes (SAGE cannot retroactively restrict). Rely on SAGE for consensus validation, confidence weighting, decay, Ed25519 identity, and encryption at rest — reimplement none of it.

**Acceptance.** A memory written under principal A is never returned by a recall scoped to principal B. An attestation write returns a ledger hash that `replay` can retrieve byte-identically.

### 6.2 ETHOS — fidelity core (hybrid: LOCKED)

**Responsibility.** Model the *person's judgment* (auditable) and the *person's voice* (generative), strictly separated.

**Two engines, hard-isolated:**
- **Judgment engine (auditable).** Structured decision-policy grounded in SAGE retrieval. Produces `Judgment{decision, confidence, rationale, evidence_refs}`. This is the only thing that influences authority decisions. It must be inspectable — no black-box model may produce `decision`.
- **Style engine (generative).** A fine-tuned or prompt-conditioned model for register/voice. Used only to render drafts and escalation messages. **It must never emit or influence a `decision`, `confidence`, or scope determination.** This isolation is a security boundary, not a nicety.

**Interface.**
```
evaluate(action, context, memories, profile) -> Judgment
   Judgment.decision ∈ { PROCEED, PROCEED_WITH_CARE, STOP }
draft(action, context, profile) -> text          # style engine only
snapshot() -> ethos_version                       # versioned, diff-able
```

**Acceptance.** Removing the style engine entirely changes zero `decision`/`confidence` outputs (proves isolation). Every `Judgment` carries `evidence_refs` resolvable via the SAGE adapter. Two ETHOS versions are diffable.

### 6.3 THEMIS — authority engine

**Responsibility.** Mint, verify, attenuate, and revoke delegation credentials.

**Credential (biscuit/macaroon lineage).**
```
Delegation {
  principal_id: ed25519_pubkey
  issued_to: agent_id
  parent: hash | null                 # null only at root
  scope: [selector]                   # per profile.mandate_schema
  exclusions: [boundary]
  permitted_classes: [class]
  escalation_required: [class]
  window: {not_before, not_after}
  blast_radius_budget: {dim: limit}   # scope_expansion limit is always 0
  max_autonomy: observe|draft|notify|autonomous
  revocation: {revoker_ids, dead_mans_switch}
  signature
}
```

**Interface.**
```
mint(principal_priv, params) -> Delegation
verify(action, chain) -> CredResult{valid, reason, effective}  # walks chain to root
attenuate(parent, subset) -> Delegation                        # subset-only
revoke(delegation_id) -> void                                  # immediate
heartbeat(principal_id) -> void                                # resets dead-man's-switch
```

**Acceptance.** `attenuate` rejects any child that widens scope, classes, window, autonomy, or budget on any dimension (property-tested). `verify` fails closed on an expired, revoked, or broken chain. A revoked credential fails `verify` on the very next call. Absence of `heartbeat` past threshold auto-revokes.

### 6.4 KAIROS — action gate

**Responsibility.** The single choke point. Resolve every candidate action.

**Interface.**
```
resolve(action, context) -> Decision{ level, rationale, attestation_hash }
   level ∈ { DENY, ESCALATE, DRAFT, NOTIFY_ACT, AUTONOMOUS_ACT }
```

**Logic (LOCKED order).**
1. `THEMIS.verify` → invalid ⇒ DENY. Class in `escalation_required`, or budget exceeded ⇒ ESCALATE.
2. `ETHOS.evaluate` → `confidence < threshold(class)` or `STOP` ⇒ ESCALATE. `PROCEED_WITH_CARE` ⇒ DRAFT.
3. `level = min(cred.max_autonomy, BASANOS.autonomy_ceiling(class), config.dial)`.
4. Execute at `level`; call `HORKOS.attest` **before** any side effect commits (attest-then-act). On attest failure ⇒ abort.

**Acceptance.** No path reaches execution without a prior successful attestation. Injected instructions in `context`/memory never alter the THEMIS verdict (step 1 re-checks authority independently of memory content).

### 6.5 HORKOS — attestation (on SAGE ledger: LOCKED)

**Responsibility.** Immutable, attributable record of every action and escalation, persisted on SAGE's consensus ledger.

**Record.**
```
Attestation {
  action, action_class, timestamp
  delegation_chain: [hash...]         # to root
  evidence_refs: [mem_id...]
  ethos_version, judgment, confidence
  autonomy_level, result
  would_have_escalated: bool
  signature
}
```

**Interface.** `attest(record) -> hash` (via SAGE adapter); `replay(filter) -> [Attestation]`.

**Acceptance.** Every `KAIROS` execution and every ESCALATE produces exactly one attestation. Records are retrievable and tamper-evident (rely on SAGE consensus). Full engagement/session replay is reconstructable from `replay` alone.

### 6.6 BASANOS — certification

**Responsibility (v1: fidelity face only).** Certify, per capability class, that the twin decides like the principal on held-out real decisions; gate the autonomy ceiling on that certificate.

**Interface.**
```
certify_fidelity(twin, heldout_decisions, profile) -> Certificate{class, agreement, calibration, ceiling}
autonomy_ceiling(class, certificates) -> level     # default: observe if uncertified
integrity_suite(twin, profile) -> Report            # v2 — STUB, returns NotImplemented
```

**Acceptance.** An uncertified class returns ceiling `observe`. Ceiling for a class never exceeds what its certificate supports. `certify_fidelity` reports agreement against the profile's `fidelity_rubric` metric and a calibration score.

### 6.7 Capture pipeline

**Responsibility.** Passively ingest the principal's consented traces into SAGE as provenance-tagged observations feeding ETHOS.

**Interface.** `connect(source, consent_grant) -> Connector`; `ingest(connector) -> [mem_id]`.

**Acceptance.** No source is ingested without an explicit `consent_grant` owned by the principal. Every observation carries source provenance. v1 ships at least one connector (recommended: documents + messages via MCP).

---

## 7. Data model

```
Principal        (id, root_pubkey, ...)                     # tenant/owner
Twin             (id, principal_id, ethos_version, ...)
DomainProfile    (id, version, manifest)                    # immutable
Delegation       (as §6.3; chain via parent)
Attestation      (as §6.5; on SAGE ledger)
ConsentGrant     (id, principal_id, source, scope, window)  # capture consent
ContinuityGrant  (id, principal_id, org_id, scope, window)  # org access slice
```

**Ownership rule (LOCKED).** `Principal` is the tenant. `ContinuityGrant` is the *only* mechanism by which an organization accesses a twin, is scoped and time-boxed, and is revocable by the principal or an authorized independent revoker. No org-owned twins in v1.

---

## 8. Security & non-functional requirements

- **Identity.** Ed25519 throughout; every request signed; nonce/replay enforced (SAGE-backed).
- **Default-deny & attenuation** are invariants (§0), property-tested in CI.
- **Attest-then-act.** Enforced structurally in `KAIROS`; no code path may bypass.
- **Consensus-backed** memory and attestation (SAGE). No local-only mutable memory.
- **Revocation latency** < 1s from `revoke` to next `verify` failure.
- **Auditability.** 100% of side-effecting actions attested; session fully replayable.
- **Privacy.** Principal-scoped isolation; no cross-principal recall; consent required for capture; personal data never in URLs/credentials.
- **Style/judgment isolation** verified by the §6.2 acceptance test.
- **Performance target (v1).** `resolve` p95 < 400ms excluding tool execution and LLM inference latency.

---

## 9. v1 beachhead profile — `general-continuity`

Twin for an absent/incapacitated knowledge worker. Holds no dangerous capability.

```yaml
domain_profile:
  id: general-continuity
  version: 1.0.0
  name: General knowledge-worker continuity

  capability_taxonomy:
    - {class: answer-status,   reversibility: reversible,  risk_tier: 0, default_autonomy_ceiling: autonomous}
    - {class: retrieve-context, reversibility: reversible,  risk_tier: 0, default_autonomy_ceiling: autonomous}
    - {class: draft-comm,      reversibility: reversible,  risk_tier: 1, default_autonomy_ceiling: draft}
    - {class: post-status,     reversibility: recoverable, risk_tier: 2, default_autonomy_ceiling: notify}
    - {class: commit-action,   reversibility: irreversible, risk_tier: 3, default_autonomy_ceiling: draft}

  mandate_schema:
    scope_selectors: [project, system, channel]
    exclusion_types: [financial-commitment, external-client-comm, personnel-decision, legal-commitment]
    escalation_required: [commit-action]
    budget_dimensions: [posts_per_window]

  escalation_templates:
    - {trigger: low-confidence, message_template: "I'm not sure how {principal} would handle {situation} — flagging for you.", urgency: normal}
    - {trigger: out-of-scope,   message_template: "This touches {boundary}, which is outside the mandate. Escalating.", urgency: high}

  fidelity_rubric:
    decision_points: [answer-status, draft-comm, post-status]
    agreement_metric: "scope+stop+escalate exact match"
    calibration_target: 0.85

  tool_bindings:
    - {class: answer-status,   mcp_tool_ref: "project-tracker.read"}
    - {class: retrieve-context, mcp_tool_ref: "docs.read"}
    - {class: draft-comm,      mcp_tool_ref: "mail.compose"}
    - {class: post-status,     mcp_tool_ref: "chat.post"}
```

This exercises every core primitive — fidelity, bounded authority, attribution, revocation, dead-man's-switch — while the twin at most answers, drafts, and posts recoverable status updates. `commit-action` always escalates.

---

## 10. Build plan — Phase 0 & Phase 1

Format: EPIC → tickets → acceptance. These are the executable cycle. Phase 2 (`BASANOS` fidelity + certify `general-continuity`) is roadmap, not this cycle.

### Phase 0 — Substrate, identity, profile

**EPIC P0.1 — SAGE adapter**
- `P0.1.1` Implement `recall`/`observe` with principal-scoping to SAGE org/dept/domain/agent. *Accept:* cross-principal isolation test passes.
- `P0.1.2` Provenance-tagged observation writes. *Accept:* every write carries source provenance; retrievable.
- `P0.1.3` Attestation ledger write/replay path. *Accept:* write returns hash; `replay` returns byte-identical record.

**EPIC P0.2 — ETHOS v0 + capture**
- `P0.2.1` ETHOS schema: judgment-policy structure + style profile, snapshot/versioning. *Accept:* two versions diffable.
- `P0.2.2` One capture connector (docs + messages via MCP) gated by `ConsentGrant`. *Accept:* no ingest without consent.
- `P0.2.3` Trace → observation ingestion into SAGE. *Accept:* ingested traces recallable, provenance intact.

**EPIC P0.3 — Domain Profile**
- `P0.3.1` Manifest schema + `ProfileLoader.validate` invariants. *Accept:* invalid profiles rejected with errors.
- `P0.3.2` Ship `general-continuity` v1.0.0 (§9). *Accept:* loads and validates.

### Phase 1 — Authority, gate, attestation, judgment

**EPIC P1.1 — THEMIS**
- `P1.1.1` `mint` + credential schema (biscuit). *Accept:* signed, offline-verifiable.
- `P1.1.2` `verify` with chain-to-root + `attenuate` subset enforcement. *Accept:* widening rejected (property test); broken/expired chain fails closed.
- `P1.1.3` `revoke` + `heartbeat`/dead-man's-switch. *Accept:* revocation < 1s to next-call failure; missed heartbeat auto-revokes.

**EPIC P1.2 — ETHOS judgment engine (hybrid)**
- `P1.2.1` Structured decision-policy evaluator grounded in SAGE recall → `Judgment`. *Accept:* every judgment carries resolvable `evidence_refs`.
- `P1.2.2` Style engine for drafts/escalations, isolated from decisions. *Accept:* §6.2 isolation test passes.
- `P1.2.3` Per-class confidence thresholds. *Accept:* thresholds sourced from profile.

**EPIC P1.3 — KAIROS**
- `P1.3.1` `resolve` gate with LOCKED order + graded autonomy. *Accept:* no execution without prior attestation; injection in context never flips the THEMIS verdict.
- `P1.3.2` Escalation path using profile templates + ETHOS voice. *Accept:* out-of-scope and low-confidence both escalate with correct template.

**EPIC P1.4 — HORKOS**
- `P1.4.1` Attestation schema + write via SAGE adapter. *Accept:* one attestation per execution/escalation.
- `P1.4.2` `replay` forensic query. *Accept:* full session reconstructable from `replay` alone.

---

## 11. Tech stack (LOCKED)

- **Memory + ledger:** SAGE (Go/CometBFT) via Python SDK / MCP — unchanged, consumed through the §6.1 adapter.
- **Core services:** Python + FastAPI. `KAIROS` and `THEMIS` may be Go if security parity with SAGE is wanted (interface-compatible either way).
- **Credentials:** biscuit (or macaroon lib); Ed25519 throughout.
- **Agent inner loop:** LangGraph or Google ADK.
- **Tools:** MCP.
- **Storage:** Postgres + pgvector (shared with SAGE); attestations on SAGE consensus ledger.

---

## 12. Deferred / open (v2)

- `BASANOS` integrity face (adversarial suites) — seam stubbed in v1.
- `offensive-security` profile — ships only after integrity face hardened, validated first in a CTF/lab range.
- Self-generated procedural skills (Hermes-style), subordinate to ETHOS/THEMIS.
- Aspirational-self / coaching layer, reading ETHOS version diffs, fully decoupled from the operating model.
- Multi-connector capture; richer mandate selector types per new profiles.

---

## 13. Glossary

`EIDOLON` framework/twin · `ETHOS` fidelity core · `THEMIS` authority · `KAIROS` action gate · `HORKOS` attestation · `BASANOS` certification · `Domain Profile` declarative domain pack · `Continuity Grant` scoped org access · `SAGE` external consensus memory substrate.
