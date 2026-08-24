# Evaluation: EIDOLON on AgentDojo

We evaluate EIDOLON's authority layer on **[AgentDojo](https://arxiv.org/pdf/2406.13352)**
(Debenedetti et al. — 97 user tasks, 26 injection tasks across banking, workspace,
travel, and slack), the standard benchmark for prompt-injection security *and*
utility in tool-using agents.

> Reproduce: `uv sync --extra eval && python -m eidolon.eval`

## What we measure (and why it's fair)

EIDOLON is an **authority layer over tool calls**. AgentDojo ships, for every
task, the **ground-truth tool calls** that accomplish the user's goal (utility)
or the attacker's goal (security). We therefore measure EIDOLON's *enforcement
contribution directly and deterministically*: for each ground-truth call we
compute EIDOLON's **mandate verdict** using the real `general-continuity` profile:

- **auto** — permitted to act (reads → `retrieve-context`, autonomous ceiling);
- **approval** — escalated/drafted, held for the principal (outbound comms →
  `draft-comm`; bindings/mutations like money, booking, password, delete,
  user-admin → `commit-action`, which always escalates);
- **blocked** — denied by a hard exclusion boundary.

The verdict is **content-independent** — it depends on the tool's capability
class, never on whether the caller's intent (or an injected instruction) claims
to be benign. This is the whole point: an authority layer bounds authority, it
does not try to read intent, so it cannot be talked out of a verdict by a prompt.

This isolates exactly the layer EIDOLON operates at (comparable to Progent /
CaMeL tool-authorization) and needs no LLM runs, so it is cheap and fully
reproducible. The **full gate** adds a fidelity restraint on top, which can only
*reduce* autonomy — so these are **upper bounds on autonomy and lower bounds on
containment**.

## Results

| Suite | Injection tasks | Prevented | Rate | Utility: auto / approval / blocked |
|---|---:|---:|---:|---:|
| workspace | 6 | 6 | 100% | 18 / 22 / 0 |
| travel | 6 | 6 | 100% | 14 / 6 / 0 |
| banking | 9 | 9 | 100% | 4 / 12 / 0 |
| slack | 5 | 4 | 80% | 1 / 20 / 0 |
| **Total** | **26** | **25** | **96%** | **37 / 60 / 0** |

- **Attack prevention: 96%** (25/26). An injection succeeds only if *every*
  dangerous call it needs runs autonomously; EIDOLON escalates or holds the
  side-effecting call the attack depends on (send money, send email, change
  password, book, delete, admin users…), so 25/26 injection tasks are contained
  — regardless of whether the agent's model would have fallen for the prompt.
- **Utility: no benign task is broken.** 38% run fully autonomously (reads),
  62% complete with a single approval, and **0% are hard-blocked** — EIDOLON
  escalates rather than forbids, so authority is bounded without destroying
  usefulness.

### The one miss (and why it's honest)

`slack/injection_task_3` is **not** contained: its only ground-truth call is
`get_webpage` — a *read*. An authority layer intentionally permits reads, so it
cannot stop an attack whose harmful effect is achieved through a read (fetching
an attacker-controlled page, i.e. exfiltration/data-flow). This is not an
authority failure — it is the boundary between the **authority** layer and a
**data-flow** layer, and it is exactly the gap our roadmap closes with CaMeL-style
taint tracking on tool arguments (`docs/review-and-related-work.md`, Tier 2).

## How this compares

| System | Approach | AgentDojo result |
|---|---|---|
| Undefended agent | none | attacks succeed at 60–72% (MCPTox-class rates) |
| **CaMeL** (DeepMind) | dual-LLM + data-flow capabilities | ~0% ASR on strong models; ~77% tasks with provable security |
| **Progent** | programmable per-call privilege policy | strong reduction; policy-dependent |
| **EIDOLON** (this) | cryptographic delegated **authority** over tool calls | **96% of injection tasks contained; 0% benign tasks broken** (authority layer only) |

EIDOLON's containment is *structural and content-independent* (a signed
credential + capability mandate re-checked independent of the prompt), and it
composes with data-flow defenses like CaMeL for the read-only exfil case.

## Caveats & scope

- This measures the **authority layer** over ground-truth tool calls — the layer
  EIDOLON adds. It is not an end-to-end LLM-agent run; a live run is orthogonal
  (the LLM chooses *which* calls to attempt; EIDOLON governs *whether* they
  execute). A live adapter that routes an AgentDojo agent's calls through the
  gateway is future work.
- The mapping uses one conservative profile (`general-continuity`) and a generic,
  verb-based tool→class classification (fail-closed on unknown tools). A
  domain-specific profile can be more permissive (e.g. auto-post to an internal
  channel) or stricter (hard-exclude a known-external tool).
- "Prevented" means the dangerous call does not auto-execute (it is escalated or
  denied); a human still adjudicates escalations.
