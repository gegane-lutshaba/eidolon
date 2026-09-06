# EIDOLON: Provable Delegated Agency for Faithful Digital AI Twins

**A governance layer that lets a person delegate a cryptographically bounded,
revocable, fully-attributable slice of their authority to an AI agent that
decides the way they would — and can prove it.**

**Mthandazo Ndhlovu** · White paper — **Revision 2** · September 2026 · Built on
[SAGE](https://github.com/l33tdawg/sage).

> **Revision 2 — corrections and contributions welcome.** This is the second
> revision of the EIDOLON white paper. It was rewritten for clarity, and it may
> still contain mistakes. If you spot an error, disagree with a claim, or want to
> sharpen the argument, please open an issue or a pull request on the
> [repository](https://github.com/gegane-lutshaba/eidolon) and push a revision —
> this paper is meant to improve in the open.

---

## Executive summary

As AI agents acquire more autonomous capabilities, organisations face a dilemma:
either grant them full permissions and endanger safety, or restrict their
permissions and either make the task more tedious for yourself or make the agent
ineffective at executing.

EIDOLON solves this by introducing a governance layer for authority that
separates **fidelity** (assessing whether an action is in line with what the
principal would do) from **authority** (checking whether the agent is
cryptographically authorized to carry out that action).

At the heart of EIDOLON lies the **KAIROS action gate**, which subjects each
candidate action to a rigorous four-step process — an Authority check, a Fidelity
assessment, enforcement of the Autonomy Ceiling, and Attestation on a
BFT-consensus ledger — before any action that has side effects is carried out.
Because it functions as a governing MCP (Model Context Protocol) gateway, EIDOLON
can be inserted directly in front of existing agent frameworks with no code
changes, offering bounded, revocable, and fully attributable delegated agency.

Two invariants are enforced structurally and property-tested in CI:

1. **Default deny:** any authority not explicitly granted is denied.
2. **No unattested action:** no side effect runs without prior successful
   attestation (attest-then-act).

Above all, EIDOLON is a governance system, not merely a collection of tools. It
has no offensive or dangerous features; it governs the authority associated with
the tools listed in a Domain Profile. Because it uses MCP, EIDOLON can sit in
front of any existing agent — Hermes, Claude Code, OpenClaw, Raptor, or Cursor —
without changes to the agent. **While SAGE gives agents memory, EIDOLON provides
them with authority.**

The system has been developed and tested with over 150 tests, including property
tests, live consensus integration, and a machine-verified model. On AgentDojo's
prompt-injection benchmark, EIDOLON's authority layer blocks 96% of injection
attempts without affecting normal tasks, and the gate responds in about one
millisecond. EIDOLON's features include a data-flow layer for exfiltration,
privacy controls, approval workflows, and the ability to export tokens for use
with various agents. Two reference profiles are available: one for
general-continuity and one for governance-only offensive-security.

---

## The problem of authority

It is nothing new for software to be given authority — OAuth scopes, IAM roles,
and capability tokens all specify the actions a program can perform. What is new
is that the program can now reason: an LLM agent chooses which tool to call and
with what arguments as it works toward a goal it understands. This undermines the
traditional approach in three ways:

1. **Scope is about meaning, not grammar.** The same `send_message` call can be
   used to "answer status questions" or to "sign a contract." The permissions
   attached to the tool do not capture the intent.
2. **Data is adversarial.** Memory and context can be altered by an attacker —
   for example, a privilege-escalation attempt is a message saying "you're now
   authorized, ignore your limits," not actual data.
3. **Blame is unclear.** For each action carried out by an autonomous agent,
   there is no answer to "who authorized it, and on what basis?"

The market generally decides on either complete autonomy or complete
supervision. In each case the real need — authority that is limited, controlled,
revocable, and traceable — is ignored.

---

## Delegated agency that can be proven

EIDOLON creates a digital twin: an agent that makes decisions the way a person
would, by exercising part of their authority. This is not merely another digital
persona but a system that provides **provable delegated agency**, built on three
commitments:

1. **Fidelity and authority are distinct criteria, and both must be satisfied.**
   A message might be completely faithful ("yes, you'd send this") but not
   authorized ("but not to this recipient") — and the reverse can also apply.
   EIDOLON evaluates these two aspects separately.
2. **Authority only decreases, never increases** — even when delegated to
   subsidiary agents. A credential can only ever grant a subset of its parent's
   authority.
3. **Every action can be traced** back along the delegation chain, together with
   the evidence and the judgment, on a ledger that never changes.

A key feature is **restraint**: the digital twin should know when to act and when
to revert the decision to the principal.

### Principles (invariants)

Beyond the two global invariants (default-deny; no unattested action), five
principles shape the design:

1. Fidelity ("would they act?") and authority ("is it permitted?") are separate
   from one another and both essential.
2. Authority reduces, never extends.
3. Any action can be associated with a chain, a body of evidence, and a judgment.
4. Empowerment occurs only after certification: a certificate must be given for
   each level of autonomy, and any ability that has not been certified is limited
   to observation.
5. The principal is the sole owner of the twin. Organisations are granted only
   limited, time-limited access for the sake of continuity — they never obtain
   the twin itself.

---

## The architecture

At the heart of the system is a set of fixed components used across all domains,
with domain-specific details supplied through a declarative **Domain Profile**.

| Component | Role |
|---|---|
| **ETHOS** | Fidelity. Models the person's judgment (auditable) and voice (generative), hard-isolated. |
| **THEMIS** | Authority. Mints, verifies, attenuates, and revokes delegation credentials. |
| **KAIROS** | The action gate. The single choke point that resolves every candidate action. |
| **BASANOS** | Certification. Gates the autonomy ceiling on fidelity + adversarial-integrity certificates. |
| **HORKOS** | Attestation. Immutable, attributable record of every action, on the consensus ledger. |
| **SAGE** | External BFT-consensus memory + attestation ledger (the substrate). |
| **Domain Profile** | Declarative pack specialising the core for one kind of twin. |

### The action gate (KAIROS)

Every candidate action resolves through KAIROS in a locked order:

1. **Authority.** `Themis.verify` follows the credential chain all the way back
   to its root; if the credential is invalid or has been cancelled, access is
   refused. When a must-escalate class is involved or the blast-radius budget is
   exceeded, an escalation takes place. This assessment comes from the signed
   credential and is independent of both memory and the surrounding environment —
   therefore resistant to gate injection.
2. **Fidelity.** `Ethos.evaluate` reaches a decision and includes a measure of
   confidence. The decision is escalated if it is to stop, or if confidence is
   below the class threshold; if the decision is to proceed with care, it is
   drafted.
3. **Ceiling.** The level equals the lowest of `credential.max_autonomy`,
   `BASANOS.ceiling(class)`, and the config dial. Certify before you give
   control.
4. **Attest-then-act.** HORKOS performs the attestation before any side effect is
   carried out; if the attestation fails, the action is cancelled.

The possible outcomes are **DENY, ESCALATE, DRAFT, NOTIFY, and ACT**. No action
with side effects can take place unless there has first been a successful
attestation.

### Authority (THEMIS)

The credentials are biscuit/macaroon in origin: they use Ed25519 for signing,
include a chain running from parent to child, can be verified offline, and permit
only subsets to be attenuated. A delegation includes scope selectors, hard
exclusions, permitted capability classes, must-escalate classes, a validity
period, a blast-radius budget (whose `scope_expansion` is always 0), and
revocation terms such as a dead-man's switch.

`attenuate(parent, subset)` rejects every child that in any way extends the
scope, classes, window, autonomy, exclusions, or budget — a conclusion reached
through hundreds of randomized cases using Hypothesis. Verify fails closed if the
chain has expired, been revoked, or been broken. Revocation takes effect on the
very next call (in under one second), and if a heartbeat is missed, automatic
revocation occurs.

### Fidelity (ETHOS)

ETHOS has two engines, hard-isolated as a security boundary:

1. **Judgment Engine.** Auditable and uses no large language models. The
   decision — together with the degree of confidence, the reasoning, and
   references to resolvable evidence — is generated by a transparent,
   deterministic policy based on retrieval from consensus memory. This policy
   employs normalized-token relevance and an optional deterministic embedder, but
   the decision is made by applying a threshold to inspectable scores; no
   black-box model is used in reaching any decision (a determinism test ensures
   this).
2. **Design Engine.** Uses a generative model (Claude), and only for producing
   draft documents and escalation messages. It has no ability to make or
   influence decisions, confidence levels, or scope.

The separation is enforced two ways: an import-graph test ensures the judgment
package never uses the design package, and a behavioral test confirms that
removing the design engine has no effect on any decisions.

### Certification (BASANOS)

BASANOS gates the autonomy ceiling on two faces:

1. **Fidelity check.** Ensures that, for each capability class, the twin reaches
   decisions similar to the principal when handling real, previously unseen
   cases. If this is not certified, the autonomy ceiling is fixed at
   observation-only.
2. **Integrity check.** Adversarial tests including memory poisoning, injection,
   and scope evasion. A twin receives an integrity certificate only if it handles
   each attack by denying, escalating, or drafting it. Greater autonomy requires
   passing the integrity certificate.

### Attestation (HORKOS) and the ledger (SAGE)

For every action and every escalation there is exactly one attestation. It
contains the action, the class, the delegation chain all the way to the root,
references to evidence, the ETHOS version, the judgment, the confidence, the
autonomy level, the result, and a flag showing whether an escalation would have
taken place. The attestation is stored on SAGE's BFT-consensus ledger. The record
is secured by a content hash, so any tampering can be detected, and a full
session can be replayed directly from the ledger. Because EIDOLON relies on SAGE
for consensus validation, confidence weighting, decay, Ed25519 identity, and
encryption, it does not reimplement any of these.

---

## Domain profiles

A Domain Profile is a declarative package that includes a capability taxonomy
(covering reversibility and risk levels), a mandate schema (scope selectors,
exclusions, must-escalate categories, and budget dimensions), escalation
templates, a fidelity rubric, and tool bindings. It is checked against several
invariants (for instance, no irreversible category may act on its own; every
high-impact category must always require escalation). Two profiles were issued:

1. **General-continuity.** For a twin standing in for a knowledge worker who is
   absent or unavailable. It can answer status questions, prepare messages for
   approval, and post recoverable status updates — but it has no dangerous
   capabilities, and all commit-actions must be escalated.
2. **Offensive security.** A governance-only profile intended for a
   red-teamer/penetration-tester in an authorized, time-limited lab or CTF
   setting. It includes no offensive capabilities; instead it provides authority
   over a number of tools. Safety features are built in: integrity checks are
   required, all major actions must be escalated, and strict exclusions prevent
   actions that are out of scope or could be harmful.

Two further capabilities compose without weakening the core:

1. **Self-generated skills.** The twin can distil reusable procedures from
   earlier sessions, but every step of an acquired skill must pass through the
   KAIROS gate again — so a skill learned with broad authority cannot be applied
   in a situation for which the twin is not currently authorized.
2. **Aspirational-self / coaching.** Advice to the principal is derived by
   examining decision history and comparing ETHOS versions. It is completely
   separate from the decision-making process (shown by the import-graph tests)
   and has no impact on any decisions.

---

## The authority layer: MCP gateway

The approach mirrors SAGE's: a server agent is connected to MCP. EIDOLON provides
a governing MCP gateway — an MCP proxy that sits in front of the tool server
below it. Rather than pointing at the server, the agent points at the gateway,
and each tool call passes through KAIROS before it can reach the server.

A declarative policy assigns each tool to a capability class; the scope of a call
is determined by its arguments (so a request is restricted to the items it
targets); and when a tool is not mapped to any class, it falls back to the
always-escalate class. The agent itself remains unchanged. A prompt injection
that gets through tool arguments cannot increase the level of authority. If the
gateway's delegation is taken away, the next tool call fails closed within the
session.

The result: you can point Hermes, Claude Code, OpenClaw, Raptor, or Cursor at the
gateway, and each tool call will be subject to limits, control, revocability, and
traceability — with no code changes. SAGE provides the agent with memory while
EIDOLON supplies governed authority, the two working together with attestation
stored on SAGE.

---

## The data-flow layer (taint and purpose)

The authority layer decides which calls are allowed and intentionally permits
reads. Below it is a thin data-flow layer whose job is to detect damage passing
through the permitted calls, using the same enforcement mechanism: a dynamically
generated exclusion that the gate both denies and confirms.

**Taint.** The gateway tracks sensitive values returned by private reads; if such
a value appears in the arguments of an egress call (for example, in a webpage URL
or an email body), a data-exfiltration exclusion is generated — closing the
read-only exfil that the authority layer alone could not. This combines
CaMeL-style value-flow tracking with cryptographic authority.

**Purpose.** The purpose for which data was collected is retained; if a value is
passed to a tool whose purpose is incompatible, the restriction is enforced — a
GDPR-style limitation enforced structurally rather than by the model's own
judgment.

---

## Human-in-the-loop, sub-agents, payments, and standards

1. **Approval process.** When an escalation takes place, it appears as a pending
   item in the approval inbox. The principal approves by signing the specific
   action (giving a one-off, expiring authorisation), after which the gate
   carries out the action, attested. An approval only releases an escalation; it
   never grants authority over a missing credential.
2. **Sub-agent delegation.** A twin reduces its credentials when acting through a
   sub-agent, using a cryptographic subset (fewer classes, more limited scope,
   less autonomy). The chain runs all the way back to the root and can go no
   further — the principled way to describe "restricted toolsets."
3. **Payments.** Once a payment escalation is approved, it becomes a signed
   payment mandate (Intent + Cart) in AP2 form, linked to the action and its
   boundaries, and issuable only by the approving principal.
4. **Standards.** THEMIS delegation groups produce real biscuit tokens with
   native offline capabilities (for just the subset), corresponding directly to
   the IETF agent-token draft — so an EIDOLON credential can be used within the
   wider capability-token ecosystem.

---

## Security properties and threat model

- **Memory / context injection.** Authority is always checked directly against
  the signed credential at the first gate step, so conclusions are not influenced
  by memory or context. Even if memory is compromised or a directive to "ignore
  your limits" is inserted, the decision is unchanged. Confirmed by specific
  integrity tests.
- **Privilege escalation via delegation.** Attenuation only produces subsets and
  is property-tested; a child never has more privileges than its parent, and
  `scope_expansion` is limited to zero.
- **Scope evasion.** Even when a boundary-crossing action is described as
  harmless, it still lies outside scope — scope excludes actions similar to, or
  falling outside, the designated targets.
- **Runaway autonomy.** The upper bound of autonomy is the lowest of three
  factors — the credential, the certificate, and the org dial — so any capability
  that is uncertified or fails an integrity check must be supervised if it is to
  act. High-impact classes require escalation.
- **Exfiltration via an approved tool.** The data-flow layer ensures a sensitive
  value cannot end up in an egress call even if the class is permitted; closing
  the read-only exfil hole alone is not sufficient.
- **Purpose creep.** Data collected for a particular purpose cannot be used in a
  tool whose purpose is incompatible.
- **Repudiation.** Because a transaction is witnessed and then carried out with a
  consensus ledger, any side-effecting action becomes non-repudiable and
  replayable.
- **Loss of control.** Halted: any delegation's time limit can be removed on a
  sub-second basis, alongside the dead-man's-switch.

---

## Evaluation

### AgentDojo (security and utility)

We evaluated the authority layer on AgentDojo (97 user tasks and 26 injection
tasks across banking, workspace, travel, and Slack). For each task we determine
EIDOLON's mandate verdict for each tool call on the basis of the ground-truth
tool calls — a deterministic, reproducible measure that isolates the contribution
of EIDOLON.

| | Injections contained | Benign tasks broken |
|---|---|---|
| **EIDOLON authority layer** | 25 / 26 (96%) | 0 / 97 (0%) — 38% fully autonomous, 62% one-approval |

The only exception is a read-only exfil (`get_webpage`), which is then handled by
the data-flow layer. For reference, CaMeL reports 67% of attacks successfully
defended, while undefended agents' success rate varies between 60% and 72%.
EIDOLON's containment is structural and content-independent: the signed
credential is verified separately from the prompt, so an injection cannot bypass
it.

### Machine-checked model

The gate's invariants are defined in TLA+ and fully verified with the TLC model
checker: `NoUnattestedAction` (any action carried out must also be attested),
`DefaultDeny`, `ExclusionRespected`, and `AttenuationNeverWidens` all stay true
throughout the entire state space. Moreover, a deliberately constructed version
that violates attest-then-act is caught — showing the verification is meaningful.

### Automated adversarial certification

The integrity face is generative: in every round, a procedural (and optional)
Claude attacker generates new attacks involving memory poisoning, injection, or
scope evasion, and the twin obtains an acting-level certificate only if it
contains all of them across all rounds. This is a continuous adversarial
guarantee, not a fixed checklist.

### Performance and test suite

`Kairos.resolve` runs in about 1 millisecond (counting only in-memory operations,
not LLM or tool execution — roughly a 400× reduction from the 400ms target). This
figure is backed by more than 150 automated tests, including Hypothesis property
tests (e.g. attenuation-never-widens and default-deny), isolation tests
(design/judgment, coaching, and skill subordination), gate tests (attest-then-act
and injection resistance), data-flow and purpose tests, escalation/approval and
payment-mandate tests, and live SAGE integration tests (cross-principal
isolation, attest→replay at the byte level, and full-session replay).

---

## Related work and comparison

EIDOLON sits where several research fields meet, and it integrates them with two
areas that have not been widely studied: a **fidelity axis** and
**runtime-certified autonomy**. A thorough review of CaMeL, Progent, biscuit/IBCT
and the IETF agent-token draft, LlamaFirewall/NeMo, the autonomy-certificate
work, the person-twin research, and AgentDojo/ToolPrivacyBench is in
[`docs/review-and-related-work.md`](review-and-related-work.md).

| Capability | Raw MCP agent | Guardrail filters (LlamaFirewall/NeMo) | Privilege policy (Progent) | Data-flow (CaMeL) | **EIDOLON** |
|---|---|---|---|---|---|
| Bounded authority | ✗ | ✗ | ✓ (local policy) | via caps | **✓ cryptographic, attenuable** |
| Cryptographic delegation chain | ✗ | ✗ | ✗ | ✗ | **✓ (biscuit exportable)** |
| Fidelity ("would they act?") | ✗ | ✗ | ✗ | ✗ | **✓** |
| Runtime-certified autonomy | ✗ | ✗ | ✗ | ✗ | **✓** |
| Injection-resistant authority | ✗ | detection | partial | ✓ (data-flow) | **✓ (memory-blind credential)** |
| Data-flow / exfil control | ✗ | partial | partial | ✓ | **✓ (composed)** |
| Revocable < 1s / dead-man | ✗ | ✗ | ✗ | ✗ | **✓** |
| Attest-then-act on consensus | ✗ | logs | ✗ | ✗ | **✓** |
| Drop-in (no agent changes) | — | varies | ✓ | ✗ | **✓ (MCP gateway)** |

---

## Status and roadmap

The core (identity-fidelity and delegated-authority), the governance MCP gateway,
the data-flow and purpose layers, adversarial certification, the approval
workflow, sub-agent delegation, biscuit standards interop, AP2 payment mandates,
and the formal model have all been implemented and tested. The remaining work:

1. **Distributed operation** — multi-node SAGE consensus and propagation of
   revocation messages through distributed gateways (the only remaining
   infrastructure piece).
2. **Live privacy benchmark** — run ToolPrivacyBench as an executable once it is
   available (the method is already implemented).
3. **Ecosystem profiles** — finance operations, customer support, and SRE; these
   are the extensibility primitive and the business model.
4. **ETHOS fidelity grounding** — richer capture feeding, alongside a hosted
   gateway using an HTTP/streamable MCP transport and multi-principal
   organizational governance.

---

## Conclusion

There are agents capable of taking action, but none you can safely hand
responsibilities to. The thing that is missing isn't intelligence but **governed
authority** — limited, controlled, revocable, and traceable. EIDOLON offers this,
and is meant to be adopted the same way memory was: by having your existing agent
connect to it. Use SAGE to give an agent memory, and EIDOLON to grant it governed
authority.

---

*Corrections and contributions are welcome — open an issue or a pull request on
the [repository](https://github.com/gegane-lutshaba/eidolon) and push a revision.*
