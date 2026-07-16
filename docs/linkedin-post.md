# LinkedIn kit — EIDOLON

Everything you need to post. Pick a hook, attach the visuals, ship.

**Assets** (in `docs/visuals/`):
- Hero image: `visuals/architecture.png` (or `gateway.png` for the integration angle)
- Carousel (square, 1080×1080): `visuals/carousel/slide-1.png` … `slide-6.png`
- White paper to link: `docs/whitepaper.md`

> Tip: LinkedIn carousels = upload the 6 PNGs as a **document/PDF** (combine
> slides 1–6 into one PDF) or as a multi-image post. Single-image posts get the
> most reach right now — lead with `slide-1.png` or `architecture.png`.

---

## Option A — the "why" post (broad audience)

> **Can you actually let an AI agent act on your behalf?**
>
> Only if it's bounded, restrained, revocable, and fully attributable. Today's
> agents force a bad trade: over-permissioned (give it your tools and hope) or
> locked down (approve every click, and you're the bottleneck again).
>
> The missing piece isn't a smarter model. It's a **governance layer for
> authority**.
>
> So I built **EIDOLON** — provable delegated agency. It lets a person delegate a
> cryptographically bounded, revocable, fully-attributable *slice* of their
> authority to a digital twin that decides the way they would:
>
> • Fidelity ("would you act?") and authority ("is it permitted?") are separate — both must pass
> • Authority only ever *narrows*, never widens — signed, attenuable credentials
> • It escalates when unsure or out of scope, and hands the decision back
> • Every action is attested on a consensus ledger — the whole session replays
> • Revoke mid-session and the next action is denied in under a second
>
> Two invariants, property-tested: **default-deny**, and **no action without a
> prior attestation**.
>
> And it drops in front of any MCP agent (Hermes, Claude Code, Cursor…) as a
> governing gateway — zero code changes. If SAGE is the memory layer, EIDOLON is
> the authority layer.
>
> White paper + demos in the comments. What would *you* need to see before you'd
> let an agent act for you? 👇
>
> #AIAgents #AIsafety #MCP #AgenticAI #LLM #Cybersecurity #AIGovernance

*(Attach: `architecture.png`, or the 6-slide carousel.)*

---

## Option B — the "builder" post (technical audience)

> Agents can act now. Agents you can *safely delegate to*? Not yet. I built
> **EIDOLON** to close that gap — the authority layer for AI agents.
>
> Every candidate action passes one gate, in a locked order:
> 1. **Authority** — verify a signed, attenuable delegation chain to root
>    (re-derived independent of memory, so prompt injection can't widen it)
> 2. **Fidelity** — an auditable, LLM-free judgment engine decides + calibrates
> 3. **Ceiling** — min(credential, certificate, org dial); certify before empower
> 4. **Attest-then-act** — write the attestation *before* any side effect
>
> Five honest outcomes: DENY · ESCALATE · DRAFT · NOTIFY · ACT.
>
> The parts I'm proud of:
> • Attenuation is subset-only, **property-tested** with Hypothesis (a child can
>   never exceed its parent)
> • Style/judgment isolation is a security boundary — enforced by an import-graph
>   test *and* a behavioral test (remove the LLM → zero decisions change)
> • An adversarial "integrity" suite (memory-poisoning / injection / scope-evasion)
>   must be *contained* before a twin earns autonomy
> • Verified against a live BFT-consensus ledger: attest → replay, byte-identical
>
> Then I made it adoptable: a **governing MCP gateway**. Point Hermes / Claude
> Code / Raptor at it instead of the raw tool server and every tool call becomes
> governed & attested — `delete_database(prod)` escalates, an out-of-scope host
> is denied, a read runs. Zero agent changes.
>
> 100+ tests, two reference profiles, runnable demos. Repo + white paper below.
>
> #AIAgents #MCP #LLM #AIsafety #Cryptography #Cybersecurity #AgenticAI #OpenSource

*(Attach: `gateway.png` or `decision-gate.png`.)*

---

## Option C — one-liner hooks (for a short post or to A/B test)

- "I gave an AI agent real authority — and made it *prove* every action. Here's EIDOLON."
- "SAGE is the memory layer for AI agents. I built the **authority** layer."
- "Prompt injection can't escalate an agent that re-checks authority from a signed credential, not its memory. That's the whole idea behind EIDOLON."
- "The safest agent isn't the one that does the most — it's the one that knows when to hand the decision back."
- "`delete_database(prod)` → 🛑 escalated, not run. Same agent, now governed. Meet EIDOLON."

---

## Carousel captions (one per slide, if posting as a document)

1. Can you let an AI agent act on your behalf? Only if it's provable.
2. The problem: today's agents are over-permissioned (unsafe) or locked down (useless).
3. The idea: delegate a bounded, revocable slice of your authority.
4. The gate: one choke point, five honest outcomes, attest-then-act.
5. The integration: the authority layer for any MCP agent — zero changes.
6. What's real: property-tested invariants, live-ledger verified, governs real agents.

---

## First comment (drop the links here, not in the post body — better reach)

> White paper: <link to docs/whitepaper.md>
> Repo: <link to project>
> Two demos: a continuity twin ("your twin while you're away") and a governing
> MCP gateway for real agents. Feedback welcome — especially from folks shipping
> agentic tools.

---

## Hashtag bank (pick 3–6)

`#AIAgents #AgenticAI #AIsafety #AIGovernance #MCP #LLM #Cybersecurity
#Cryptography #OpenSource #DigitalTwin #TrustAndSafety #InfoSec`

---

## Notes on posting

- Lead with a **question or a concrete stakes** line; LinkedIn rewards a strong
  first sentence (it's what shows before "…see more").
- Put **links in the first comment**, not the body.
- Native images/carousels outperform link previews.
- End with a **question** to invite comments (the algorithm weights early
  comments heavily).
