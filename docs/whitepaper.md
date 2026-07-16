# EIDOLON: Provable Delegated Agency for Faithful Digital Twins

**A governance layer that lets a person delegate a cryptographically bounded,
revocable, fully-attributable slice of their authority to an AI agent that
decides the way they would — and can prove it.**

*White paper · v1 · Built on [SAGE](https://github.com/l33tdawg/sage).*

![EIDOLON architecture](visuals/architecture.png)

---

## Executive summary

AI agents can now *act* — send email, run code, deploy, execute tools over the
Model Context Protocol (MCP). But nobody can safely hand one real authority,
because today's agents force a bad choice: **over-permissioned** (give it your
tools and hope) or **locked down** (approve every step, and the human is the
bottleneck again). The missing piece isn't a smarter model — it's a **governance
layer for authority**.

EIDOLON is that layer. It separates two independent questions — *would the
principal act?* (**fidelity**) and *is the agent permitted?* (**authority**) —
and requires both to pass before any action runs. Authority is carried in
Ed25519-signed, attenuable credentials that **only ever narrow**, never widen;
it is **revocable in under a second**; and **every action is attested on a
consensus ledger**, so an entire session replays and is attributable to a
delegation chain, its evidence, and its judgment.

Two invariants are enforced structurally and property-tested in CI:

1. **Default-deny** — any authority not explicitly granted is denied.
2. **No unattested action** — no side effect runs without a prior successful
   attestation (*attest-then-act*).

Crucially, EIDOLON is **capability-agnostic governance, not tooling**. It ships
no offensive or dangerous capability; it governs *authority* over whatever tools
a declarative **Domain Profile** binds. And because it speaks MCP, it drops in
front of any existing agent — Hermes, Claude Code, OpenClaw, Raptor, Cursor — as
a **governing gateway**, with zero changes to the agent. If SAGE is *the memory
layer* agents plug in, EIDOLON is *the authority layer*.

The system is implemented and tested (100+ tests including Hypothesis property
tests and live-consensus integration), with two reference profiles
(`general-continuity` and a governance-only `offensive-security`) and runnable
demos.

---

## 1. The problem

Delegating authority to software is not new — OAuth scopes, IAM roles, and
capability tokens all bound what a program may do. What is new is that the
program now *reasons*: an LLM agent chooses which tool to call, with which
arguments, in pursuit of a goal it interprets. That breaks the classic model in
three ways:

- **Scope is semantic, not syntactic.** "Answer status questions" and "sign a
  contract" may both be a `send_message` call. Permissions on the *tool* don't
  capture the *intent*.
- **Inputs are adversarial.** Memory and context are attacker-influenced. A
  message that says *"you're now authorized, ignore your limits"* is a
  privilege-escalation attempt, not data.
- **Attribution is lost.** When an autonomous agent acts, "who authorized this,
  on what basis?" often has no answer.

The market's two responses — maximal autonomy or maximal supervision — are the
unsafe and the useless ends of the same missing axis: **governed authority that
is bounded, restrained, revocable, and attributable.**

---

## 2. Thesis: provable delegated agency

EIDOLON models a **digital twin**: an agent that decides the way a specific
person (the *principal*) would, operating under a slice of that person's
authority. The category is not "digital twin" the persona toy; it is **provable
delegated agency**. Three commitments define it:

1. **Fidelity and authority are independent axes; both must pass.** A twin may be
   perfectly faithful ("yes, you'd send this") yet unauthorized ("but not to
   this recipient") — and vice versa. EIDOLON evaluates them separately.
2. **Authority attenuates, never widens** — including twin → sub-agent
   delegation. A credential can only ever grant a subset of its parent.
3. **Every action is attributable** to a delegation chain, its evidence, and its
   judgment, on an immutable ledger.

Restraint is the product. The twin's job is often *not to act* — to recognise
the edge of its mandate and hand the decision back.

---

## 3. Principles (invariants)

Beyond the two global invariants (default-deny; no unattested action), five
principles shape the design:

- Fidelity ("would they act?") and authority ("is it permitted?") are separate
  and both required.
- Authority attenuates, never widens.
- Every action is attributable to a chain, evidence, and judgment.
- **Certify before you empower.** An autonomy level requires a matching
  certificate; uncertified capability is capped at *observe*.
- **The principal owns the twin.** Organizations receive scoped, time-boxed
  *continuity grants* — never org-owned twins.

---

## 4. Architecture

The core is a fixed, domain-agnostic set of components. Everything
domain-specific enters through a declarative **Domain Profile**.

| Component | Role |
|---|---|
| **ETHOS** | *Fidelity.* Models the person's judgment (auditable) and voice (generative), hard-isolated. |
| **THEMIS** | *Authority.* Mints, verifies, attenuates, and revokes delegation credentials. |
| **KAIROS** | *The action gate.* The single choke point; resolves every candidate action. |
| **BASANOS** | *Certification.* Gates the autonomy ceiling on fidelity + adversarial-integrity certificates. |
| **HORKOS** | *Attestation.* Immutable, attributable record of every action, on the consensus ledger. |
| **SAGE** | External BFT-consensus memory + attestation ledger (the substrate). |
| **Domain Profile** | Declarative pack specialising the core for one kind of twin. |

### 4.1 The action gate (KAIROS)

![The KAIROS decision gate](visuals/decision-gate.png)

Every candidate action resolves through KAIROS in a **locked order**:

1. **Authority** — `THEMIS.verify` walks the credential chain to root. Invalid or
   revoked ⇒ **DENY**. A must-escalate class, or a blast-radius budget exceeded ⇒
   **ESCALATE**. *This step is re-derived from the signed credential, independent
   of memory or context* — which is what makes the gate injection-resistant.
2. **Fidelity** — `ETHOS.evaluate` produces a decision and calibrated confidence.
   STOP or confidence below the class threshold ⇒ **ESCALATE**;
   proceed-with-care ⇒ **DRAFT**.
3. **Ceiling** — `level = min(credential.max_autonomy, BASANOS.ceiling(class),
   config.dial)`. Certify before empower.
4. **Attest-then-act** — `HORKOS` writes the attestation *before* any side
   effect commits. If attestation fails, the action aborts.

The five outcomes — **DENY, ESCALATE, DRAFT, NOTIFY, ACT** — are honest by
construction: no path reaches a side effect without a prior successful
attestation.

### 4.2 Authority (THEMIS)

Credentials are of biscuit/macaroon lineage: Ed25519-signed, chained
parent→child, offline-verifiable, and **attenuable subset-only**. A delegation
carries scope selectors, hard exclusions, permitted capability classes,
must-escalate classes, a validity window, a blast-radius budget (whose
`scope_expansion` dimension is always 0), a maximum autonomy level, and
revocation terms including a **dead-man's-switch**.

`attenuate(parent, subset)` rejects any child that widens scope, classes, window,
autonomy, exclusions, or budget on any dimension — a property proved over
hundreds of randomized cases with Hypothesis. `verify` fails closed on an
expired, revoked, or broken chain. **Revocation takes effect on the very next
call** (< 1s), and a missed heartbeat auto-revokes.

### 4.3 Fidelity (ETHOS)

ETHOS has two engines, hard-isolated as a *security boundary*:

- **Judgment engine** — auditable and **LLM-free**. A transparent, deterministic
  policy grounded in consensus-memory retrieval produces the decision,
  confidence, rationale, and resolvable evidence references. No black-box model
  may produce a decision.
- **Style engine** — generative (Claude). It renders *voice* for drafts and
  escalation messages only. It may never emit or influence a decision,
  confidence, or scope.

The isolation is enforced two ways: an **import-graph test** proves the judgment
package never imports the style package, and a **behavioral test** proves that
removing the style engine changes zero decisions.

### 4.4 Certification (BASANOS)

BASANOS gates the autonomy ceiling on two faces:

- **Fidelity face** — certifies, per capability class, that the twin decides like
  the principal on held-out real decisions. Uncertified ⇒ ceiling *observe*.
- **Integrity face** — runs adversarial suites (**memory-poisoning, injection,
  scope-evasion**). A twin earns an integrity certificate only if every
  adversarial case is *contained* (denied, escalated, or at most drafted). Where
  integrity gating is required, an autonomy level above *draft* also requires a
  passing integrity certificate.

### 4.5 Attestation (HORKOS) and the ledger (SAGE)

Each action and escalation yields exactly one attestation — action, class,
delegation chain to root, evidence references, ETHOS version, judgment,
confidence, autonomy level, result, and a would-have-escalated flag — persisted
on SAGE's BFT-consensus ledger. The record is content-hashed and
tamper-evident; a full session **replays from the ledger alone**. EIDOLON relies
on SAGE for consensus validation, confidence weighting, decay, Ed25519 identity,
and encryption — it reimplements none of it.

---

## 5. Domain Profiles

A Domain Profile is a declarative pack — capability taxonomy (with reversibility
and risk tier), mandate schema (scope selectors, exclusions, must-escalate
classes, budget dimensions), escalation templates, fidelity rubric, and tool
bindings — validated against invariants (e.g. *no irreversible class may act
autonomously*; *every high-impact class must always escalate*). Two ship:

- **`general-continuity`** — a twin for an absent or incapacitated knowledge
  worker. It answers status questions, drafts communications for approval, and
  posts recoverable status updates — and holds no dangerous capability.
  `commit-action` always escalates.
- **`offensive-security`** — a *governance-only* pack for a red-teamer twin
  confined to an authorized, time-boxed lab/CTF engagement. Consistent with the
  permanent non-goal, **it ships no offensive capability**; it governs authority
  over range-bound tools. It is safe-by-construction: integrity-gated by
  default, every impactful class (exploit, credential-use, lateral-movement,
  persistence) always escalates, and hard exclusions deny out-of-scope targets,
  production, third parties, exfiltration, destruction, and DoS.

Two further capabilities compose without weakening the core:

- **Self-generated skills** (Hermes-style procedural memory) — the twin learns a
  reusable plan from a completed session. Skills are **subordinate to the gate**:
  replaying a skill re-resolves every step through KAIROS, so a skill learned
  under broad authority yields nothing it isn't currently authorized for.
- **Aspirational-self / coaching** — reads decision history and ETHOS version
  diffs to advise the principal. It is **fully decoupled**: an import-graph test
  proves the decision path never imports it, and it changes zero decisions.

---

## 6. The authority layer: MCP gateway

![The authority layer for any MCP agent](visuals/gateway.png)

Adoption follows the pattern SAGE used: *be a server agents plug in over MCP.*
EIDOLON ships a **governing MCP gateway** — an MCP proxy that fronts a downstream
tool server. An agent points at the gateway instead of the raw server, and every
`tools/call` is routed through KAIROS before it can touch the real tool:

- an **acting** decision forwards to the real tool and returns its result — the
  attestation is already written (*attest-then-forward*);
- **draft / escalate / deny** return a structured refusal; the tool is never
  called.

A tool is mapped to a capability class by a declarative policy; a call's scope is
derived from its arguments (so a request is bounded by *what it targets*); and an
**unmapped tool fails closed** to the always-escalate class. The agent is
unchanged. A prompt-injection smuggled through tool arguments cannot widen
authority. Revoke the gateway's delegation and the next tool call fails closed,
mid-session.

The result: point Hermes, Claude Code, OpenClaw, Raptor, or Cursor at the
gateway and — with zero code changes — every tool call becomes bounded,
restrained, revocable, and attributable. SAGE gives the agent memory; EIDOLON
gives it governed authority; and they compose (attestations live on SAGE).

---

## 7. Security properties & threat model

- **Prompt injection / memory poisoning.** Authority is re-derived from the
  signed credential at gate step 1, independent of memory or context. A poisoned
  memory or an "ignore your limits" injection cannot flip the verdict — verified
  by the integrity suite and dedicated tests.
- **Privilege escalation via delegation.** Attenuation is subset-only and
  property-tested; a child can never exceed its parent, and `scope_expansion` is
  budgeted to zero.
- **Scope evasion.** A boundary-crossing action mislabeled as benign is still
  denied by its exclusions; look-alike/out-of-grant targets are denied by scope.
- **Runaway autonomy.** The autonomy ceiling is `min` of credential, certificate,
  and org dial; uncertified or integrity-failing capability cannot act
  unattended. High-impact classes always escalate.
- **Repudiation.** Attest-then-act plus a consensus ledger make every
  side-effecting action non-repudiable and replayable.
- **Loss of control.** Sub-second revocation and a dead-man's-switch bound the
  window of any delegation.

---

## 8. Evaluation

The implementation is validated by 100+ automated tests, including:

- **Property tests** (Hypothesis) that attenuation never widens authority across
  randomized credentials, and default-deny holds.
- **Isolation tests** — ETHOS style/judgment separation (import-graph +
  behavioral), coaching decoupling (import-graph + behavioral), skill
  subordination ("cannot smuggle authority").
- **Gate tests** — attest-then-act (no execution without a prior attestation),
  injection-resistance, per-class outcomes.
- **Adversarial tests** — the integrity suite contains memory-poisoning,
  injection, and scope-evasion cases.
- **Live-consensus integration** — against a Dockerized SAGE node: cross-principal
  isolation, attest→replay byte-identical, and a full multi-class session
  reconstructable from the ledger.
- **Gateway tests** — the real tool runs only when authorized, every call is
  attested, fail-closed on unknown tools, arg-derived scope denies out-of-grant
  targets, injection through arguments never widens authority.

---

## 9. Comparison

| | Raw MCP agent | Approval-gated agent | Policy/guardrail filters | **EIDOLON** |
|---|---|---|---|---|
| Bounded authority | ✗ | partial (manual) | class-level | cryptographic, attenuable |
| Restraint (escalate/hand-back) | ✗ | human-driven | block/allow | graded (deny/escalate/draft/notify/act) |
| Revocable mid-session | ✗ | ✗ | redeploy | < 1s, dead-man's-switch |
| Attribution / audit | logs | logs | logs | consensus-ledger attestation, replayable |
| Injection-resistant authority | ✗ | ✗ | best-effort | authority is memory-blind |
| Drop-in (no agent changes) | — | ✗ | varies | MCP gateway, zero changes |

---

## 10. Roadmap

- Additional Domain Profiles (finance ops, customer support, SRE) contributed by
  an ecosystem — the profile is the extensibility primitive and the business
  model.
- Richer capture connectors feeding ETHOS fidelity grounding.
- Hardening the integrity face into a continuous certification pipeline.
- Multi-principal continuity grants and organizational governance tooling.
- HTTP/streamable MCP transport and a hosted gateway.

---

## 11. Conclusion

Agents that can act are here; agents you can *safely delegate to* are not. The
gap is not intelligence — it is governed authority: bounded, restrained,
revocable, attributable. EIDOLON is that layer, and it is designed to be
adopted the way memory was — as a server your existing agent plugs into. Give an
agent memory with SAGE; give it governed authority with EIDOLON.

---

*Glossary — EIDOLON: framework/twin · ETHOS: fidelity · THEMIS: authority ·
KAIROS: action gate · HORKOS: attestation · BASANOS: certification · Domain
Profile: declarative domain pack · SAGE: external consensus memory substrate.*
