# EIDOLON — Project Review, Related Work, and the Gap We Cover

*A critical review of the current implementation, a literature review of adjacent
research (as of Aug 2026), an honest positioning against it, and a prioritized
roadmap of improvements and extensions.*

---

## Part 1 — Project review

### 1.1 What exists today

~5.3k LOC across a clean, ports-and-adapters core (26 test modules; 100+ tests
including Hypothesis property tests and live-consensus integration):

- **THEMIS** — Ed25519-signed, chained, **attenuable** delegation credentials
  (biscuit/macaroon lineage); subset-only attenuation (property-tested);
  revocation < 1s; dead-man's-switch.
- **ETHOS** — fidelity core with two **hard-isolated** engines: an auditable,
  LLM-free judgment engine and a Claude style engine (import-graph + behavioral
  isolation tests).
- **KAIROS** — the single action gate; LOCKED order; **attest-then-act**;
  injection-resistant (authority re-derived independent of memory/context).
- **BASANOS** — certification: a fidelity face and an adversarial **integrity**
  face (memory-poisoning / injection / scope-evasion suites) that gate the
  autonomy ceiling.
- **HORKOS + SAGE** — attestations on a BFT-consensus ledger; attributable to a
  delegation chain, evidence, and judgment; full session replay.
- **Domain Profiles** — `general-continuity` and a governance-only
  `offensive-security`; skills (subordinate to the gate) and a decoupled coaching
  layer.
- **Governing MCP gateway** — drop-in authority layer for any MCP agent; a Hermes
  before/after case study; a web dashboard; CLI showcases.

### 1.2 Strengths

- **A coherent, enforced model**, not a checklist: two invariants (default-deny;
  no unattested action) are structural and property-tested.
- **Injection resistance by construction** — authority is a signed credential
  re-checked independent of untrusted input; it is not a classifier that can be
  evaded.
- **Separation of concerns** that the field usually conflates: *fidelity* (would
  the principal act?) vs *authority* (is it permitted?) vs *certification* (has
  it earned this autonomy?).
- **Adoptability** — the MCP gateway means zero agent changes; it composes with
  existing assistants (Hermes/OpenClaw) rather than replacing them.

### 1.3 Weaknesses & limitations (honest)

1. **The judgment engine is an MVP.** Fidelity grounding is lexical-overlap over
   recalled memories — deliberately simple and inspectable, but not yet a
   faithful decision model. This is the single weakest component.
2. **No standard-benchmark evaluation.** We have not run AgentDojo / ToolEmu /
   AgentHarm; the field measures utility-under-attack there, and we currently
   can't cite a number.
3. **Bespoke credential format.** THEMIS reinvents attenuable tokens rather than
   emitting biscuit/UCAN or aligning to the emerging IETF agent-token draft —
   limiting interop with the wider agent ecosystem.
4. **No cross-call data-flow control.** The gate governs *authority per call* but
   does not track data provenance across calls, so exfiltration *through an
   otherwise-allowed tool* isn't caught the way CaMeL's data-flow typing catches
   it.
5. **Escalation is a return value, not a workflow.** There's no approval
   inbox/queue, approval tokens, or SLA — needed for real human-in-the-loop use.
6. **Adversarial suites are hand-written.** The integrity face uses fixed cases,
   not an automated attacker generating fresh injections.
7. **Performance unmeasured.** The PRD's p95 < 400ms target for `resolve` is not
   yet benchmarked (recall + optional LLM in the path).
8. **Single-node substrate in practice.** SAGE runs personal-mode; multi-node
   consensus, and revocation propagation across distributed gateways, are
   untested.

---

## Part 2 — Related work (literature review)

The relevant field splits into seven strands. For each: what it does, and how
EIDOLON relates.

### 2.1 Prompt-injection defense
- **CaMeL — "Defeating Prompt Injections by Design"** (Google DeepMind, arXiv
  [2503.18813](https://arxiv.org/pdf/2503.18813)). A dual-LLM design (privileged
  + quarantined) that extracts control/data flow from the trusted query and
  applies **capabilities** at tool-call time so untrusted data can't alter
  program flow or exfiltrate. ~77% of AgentDojo tasks solved *with provable
  security*. **Closest in spirit** to EIDOLON's "authority independent of
  untrusted data," but CaMeL governs *data/control flow within one agent's
  execution*; EIDOLON governs *delegated authority* (credentials, attenuation,
  revocation, attribution) across agents and adds fidelity + certification.
- **MELON** ([2502.05174](https://arxiv.org/pdf/2502.05174)), **Meta SecAlign**
  ([2507.02735](https://arxiv.org/pdf/2507.02735)) — provable/model-level IPI
  defenses. Model-centric; EIDOLON is model-agnostic enforcement.
- **LlamaFirewall** (Meta, [2505.03574](https://arxiv.org/abs/2505.03574)),
  **NeMo Guardrails** (NVIDIA), **Invariant** — runtime *detection* guardrails
  (jailbreak classifier, alignment/CoT audit, code scan). Best-effort detection;
  EIDOLON is enforcement (authority), not detection.

### 2.2 Least-privilege & policy enforcement
- **Progent — "Programmable Privilege Control for LLM Agents"**
  ([2504.11703](https://arxiv.org/pdf/2504.11703)). Symbolic policy over tool
  names/args; every call checked deterministically; an LLM drafts/updates the
  policy with an SMT solver classifying updates as *narrowing* (auto) vs
  *expansion* (approval). **Very close** to EIDOLON's gateway policy layer.
  Difference: Progent is *local policy*; EIDOLON is cryptographic *delegation*
  (chain-to-root, revocable, attributable) plus fidelity, certification, and
  attest-then-act. (Also AgentSpec, AgentBound.)
- Consensus best practice across the field: **"authorize outside the model" in a
  policy engine / tool gateway** — exactly EIDOLON's gateway posture.

### 2.3 Attenuable delegation credentials
- **Macaroons** (HMAC-chained caveats), **Biscuit** (Ed25519 + offline
  attenuation + Datalog), **UCAN**, **ZCAP-LD**, **WAVE**. THEMIS is squarely in
  this lineage.
- **IETF draft — "Attenuating Authorization Tokens for Agentic Delegation
  Chains"** ([draft-niyikiza-oauth-attenuating-agent-tokens](https://datatracker.ietf.org/doc/draft-niyikiza-oauth-attenuating-agent-tokens/))
  and **Invocation-Bound Capability Tokens (IBCTs)** — fuse identity +
  attenuated authorization + provenance into append-only token chains. **This is
  the standardization of what THEMIS does.** EIDOLON should interoperate rather
  than reinvent.
- Survey: *Identity Management for Agentic AI* ([2510.25819](https://arxiv.org/pdf/2510.25819)),
  *Authorization Propagation in Multi-Agent AI* ([2605.05440](https://arxiv.org/pdf/2605.05440)).

### 2.4 Agent identity & auth standards
- **MCP** mandates OAuth 2.1 + PKCE for HTTP deployments; **A2A** (Linux
  Foundation, v1.0, 2026) ships **signed Agent Cards** for verifiable identity;
  **Web Bot Auth**; **AP2** agent-payment mandates with cryptographic
  accountability. EIDOLON currently lives *below* these (an MCP gateway); it
  should map delegations to/from A2A cards and MCP OAuth scopes.

### 2.5 Audit, provenance & verifiability
- **Action Provenance Graph**, **Verifiability-First Agents**
  ([2512.17259](https://arxiv.org/pdf/2512.17259)), tamper-evident append-only
  ledgers, **remote attestation**, **AGENTSAFE** ([2512.03180](https://arxiv.org/pdf/2512.03180)).
  HORKOS is in this space. Differentiator: EIDOLON's **attest-then-act** makes
  attestation a *precondition* (structurally enforced), not after-the-fact
  logging, and anchors it on BFT consensus with attribution to chain + evidence
  + judgment.

### 2.6 Autonomy levels & certification
- **"Levels of Autonomy for AI Agents"** (Knight First Amendment Institute,
  [2506.12469](https://arxiv.org/pdf/2506.12469)); **autonomy certificates**;
  **Trust Certificate with graduated verdicts** and pre-deployment assurance
  ([2606.04037](https://arxiv.org/html/2606.04037v1)); CSA autonomy levels.
  These are mostly *pre-deployment / third-party* certification. BASANOS differs
  by wiring **per-capability-class** certificates (fidelity + adversarial
  integrity) into the **runtime** autonomy ceiling (`min(cred, cert, dial)`),
  enforced on every action.

### 2.7 Person-twins & fidelity
- **"From Role to Person: Trust Calibration in Twin Agents"**
  ([2605.19838](https://arxiv.org/pdf/2605.19838)); **Decision-Targeted Digital
  Twins** ([2606.25923](https://arxiv.org/pdf/2606.25923)); preference-based
  fair digital twins. This literature *models* a person's preferences/fidelity
  and studies trust — but **never couples fidelity to an authority/enforcement
  mechanism.** Notably it finds *higher fidelity can reduce trust* — motivating
  EIDOLON's restraint-and-attribution framing.

### 2.8 Benchmarks
- **AgentDojo** (97 tasks / 629 security cases; utility *and* security),
  **ToolEmu**, **τ-bench**, **AgentHarm**, **Agent-SafetyBench**, **LivePI**
  ([2605.17986](https://arxiv.org/pdf/2605.17986)), **ToolPrivacyBench**
  ([2606.28061](https://arxiv.org/pdf/2606.28061)). EIDOLON should be evaluated
  here.

---

## Part 3 — The gap EIDOLON covers

Each strand above solves *one* piece. **No existing system unifies them into one
runtime-enforced model of a person delegating bounded authority to a twin.**
Concretely, EIDOLON's distinctive contributions:

1. **Fidelity as a first-class, auditable security gate.** The person-twin
   literature models fidelity but never enforces with it; the security
   literature enforces authority but never models fidelity. EIDOLON makes
   *"would the principal act?"* an independent, LLM-free gate that must pass
   *alongside* *"is it permitted?"* — a separation no surveyed system has.
2. **Certify-before-empower at runtime.** Autonomy is not a config flag or a
   one-time third-party badge; it is the live `min` of a credential, a
   per-capability **behavioral + adversarial certificate**, and an org dial —
   re-checked every action.
3. **Attest-then-act on consensus.** Attestation is a *precondition*, enforced
   structurally, on a BFT ledger, attributable to chain + evidence + judgment —
   not an after-the-fact log.
4. **The unification + adoption path.** Cryptographic attenuable delegation
   (THEMIS) + fidelity (ETHOS) + certification (BASANOS) + attestation (HORKOS) +
   a **framework-agnostic MCP gateway**, framed as *sovereign, revocable personal
   delegation* — the "authority layer" that composes with the "memory layer"
   (SAGE) and with existing assistants.

**Honest overlaps** (where EIDOLON is *not* first, and should converge with the
field): attenuable tokens (biscuit/IBCT/IETF draft), tool-gateway policy
enforcement (Progent), injection-resistance-by-design (CaMeL), tamper-evident
provenance (APG/verifiability-first), and autonomy certificates (Levels of
Autonomy). EIDOLON's novelty is the *composition* plus the *fidelity* and
*runtime-certified-autonomy* primitives — not the individual security mechanisms.

### Positioning at a glance

| Capability | CaMeL | Progent | Biscuit/IBCT/IETF | LlamaFirewall/NeMo | Autonomy certs | **EIDOLON** |
|---|---|---|---|---|---|---|
| Injection-resistant authority | ✓ (data-flow) | partial | — | detection | — | ✓ (memory-blind credential) |
| Least-privilege per tool call | via caps | ✓ | ✓ (scope) | — | — | ✓ |
| Cryptographic **delegation** chain | — | — | ✓ | — | — | ✓ |
| Revocable < 1s / dead-man | — | — | partial | — | — | ✓ |
| **Fidelity** ("would they act?") | — | — | — | — | — | ✓ |
| Runtime **certified** autonomy | — | — | — | — | pre-deploy | ✓ |
| Attest-**then**-act on consensus | — | — | provenance | — | — | ✓ |
| Cross-call data-flow / exfil control | ✓ | partial | — | partial | — | ✗ *(gap → adopt)* |
| Standard token/identity interop | — | — | ✓ | — | — | ✗ *(gap → adopt)* |
| Benchmarked (AgentDojo) | ✓ | ✓ | — | ✓ | — | ✗ *(gap → do)* |

---

## Part 4 — Prioritized improvements & extensions

**Tier 1 — credibility — ✅ DONE:**
1. ✅ **Evaluated on AgentDojo** — **96% of injection tasks contained** at the
   authority layer, **0% of benign tasks broken** (38% fully autonomous, 62%
   completable with one approval). The single miss is a read-only exfil (a
   data-flow, not authority, issue → Tier 2). See [`docs/eval-agentdojo.md`](eval-agentdojo.md);
   reproduce with `python -m eidolon.eval`.
2. ✅ **Fidelity engine v2** — normalized-token Dice grounding + a pluggable,
   deterministic offline embedder (`HashingEmbedder`) + a consistency signal; the
   decision stays a transparent threshold (no black box). `certify_fidelity`
   demonstrated on a labeled held-out set.
3. ✅ **Benchmarked `resolve`** — **p95 ≈ 1 ms** (in-memory, excl. LLM/tool),
   ~400× under the 400 ms target (`examples/bench_resolve.py`).

**Tier 2 — close the honest gaps (converge with the field):**
4. ✅ **Standards interop** (`eidolon.themis.interop`) — THEMIS delegations export
   as real **biscuit** tokens (facts + a self-enforcing least-privilege check),
   with biscuit-native **offline attenuation** (subset-only) and Datalog
   authorization. Maps directly to the **IETF attenuating-agent-tokens** draft;
   MCP OAuth / A2A card mappings documented. See [`docs/standards-interop.md`](standards-interop.md).
5. ✅ **CaMeL-style data-flow / taint tracking** (`eidolon.gateway.taint`) — the
   gateway tracks sensitive values from private reads and denies-and-attests any
   egress carrying them, deriving a dynamic `data-exfiltration` exclusion so
   authority and data-flow compose through one mechanism. Closes the read-exfil
   miss from the AgentDojo eval — a novel *authority × data-flow* combination.
6. ✅ **Automated adversarial certification** (`eidolon.basanos.integrity.attacker`)
   — a `ProceduralAttacker` (offline, seeded, diverse) and an optional Claude
   `LLMAttacker` generate FRESH injections each round; `certify_integrity_adversarial`
   grants an acting-level certificate only if the twin contains every generated
   attack across all rounds. A continuous adversarial guarantee, not a checklist
   (`make adversarial`).

**Tier 3 — deployment readiness & reach:**
7. ✅ **Escalation approval workflow** (`eidolon.escalation`) — an escalated
   decision becomes a pending item in an approval inbox; the principal approves
   by *signing* the exact action (a one-time, expiring `Approval`), and KAIROS
   executes it via `resolve_with_approval` — attested. An approval only releases
   an escalation; it can't grant authority the credential lacks (revoked /
   out-of-scope / unpermitted still DENY). API endpoints + `make escalation`.
8. ✅ **Sub-agent delegation e2e** (`make subagent`) — a twin attenuates its
   delegation to a sub-agent (strict subset); the chain root→twin→sub-agent
   verifies to root and is bounded (out-of-subset class/scope → DENY); a widening
   attempt is rejected at attenuation time. Maps Hermes' "restricted toolsets" to
   a cryptographic, biscuit-exportable subset-only credential.
9. **Distributed revocation & heartbeat service**; multi-node SAGE.
10. **Purpose-binding / privacy** (cf. ToolPrivacyBench): bind captured data and
    tool use to a declared purpose in the mandate; evaluate on ToolPrivacyBench.
11. **Payments:** map `commit-action` ↔ **AP2** payment mandates.
12. **Formal model:** a small TLA+/Alloy spec of the gate order + non-bypass +
    attenuation, to upgrade the property tests to a checked model.

---

## Part 5 — Research framing (if we write it up)

- **Thesis:** *Provable delegated agency* — govern the **authority** of a
  person's digital twin, separating fidelity from permission, gating autonomy on
  runtime certification, and making every action attest-then-act on consensus.
- **Contributions:** (C1) the fidelity/authority separation as dual required
  gates; (C2) runtime certify-before-empower with adversarial integrity
  certificates; (C3) attest-then-act on a consensus ledger; (C4) a
  framework-agnostic governing MCP gateway unifying the above; (C5) two reference
  domain profiles incl. a governance-only offensive-security twin.
- **Evaluation plan:** AgentDojo (utility + security), the integrity suite vs an
  automated attacker, revocation-latency and `resolve` p95 micro-benchmarks, and
  an ablation showing each gate's contribution (esp. that authority holds with
  the fidelity/LLM removed).
- **Threats to validity:** fidelity grounding quality; reliance on correct
  tool→class mapping (mis-mapping = mis-governance — mitigated by fail-closed);
  the gateway assumes tools are only reachable *through* it; consensus-substrate
  assumptions.
- **Relation to prior art:** builds on CaMeL (injection-by-design), Progent
  (privilege control), biscuit/IBCT/IETF (attenuable delegation), APG/
  verifiability-first (provenance), and Levels-of-Autonomy (certification);
  contributes the fidelity axis, runtime-certified autonomy, attest-then-act, and
  their unification.

---

*Sources are linked inline. This document reflects the field as of Aug 2026 and
should be refreshed as AgentDojo results, the IETF agent-token draft, and A2A/MCP
authorization evolve.*
