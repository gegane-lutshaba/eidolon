# EIDOLON — 3-minute demo video script

**Format:** one continuous screen capture, no slides, voice-over. Terminal on
the left, browser on the right. Retro vibe carries itself — don't over-produce.
**Golden rule:** everything on screen is real. No mockups, no cuts that hide
steps.

---

## COLD OPEN (0:00 – 0:20) — the problem, in one action

*Screen: a terminal running Claude Code mid-task in a scratch repo.*

> "This is my coding agent. It reads my files, runs my tools, sends things on
> my behalf. It acts with **my** authority — and none of my restraint. One
> poisoned web page, one malicious dependency README, and it's *my* hands
> doing the damage.
>
> So I put it on a leash. Watch."

## INSERT COIN (0:20 – 0:50) — enroll

*Browser: eidolon.onyxcreator.com. Scroll the landing for 2 seconds — CRT
scanlines, PRESS START. Click it. Sign up. Click ENROLL NEW AGENT.*

> "This is EIDOLON. I enroll my agent, name it, and choose how much of my
> authority it gets. Not a system prompt. Not a vibe. A signed, revocable
> credential — I'll start it as a DRAFTER: it can read and draft, and
> everything else gets held."

*Wizard: name `claude-code`, pick DRAFTER, MINT CREDENTIAL. The connect modal
opens.*

## WRAP (0:50 – 1:20) — one file, zero agent changes

*Copy the gateway.yaml, save it in the repo. Copy the .mcp.json block into the
project. Restart Claude Code.*

> "One file next to my agent, one entry in its MCP config. My agent doesn't
> change at all — its tools now just happen to live behind a gate that checks
> a credential on every single call. Ed25519, checked outside the model, so
> there's nothing to prompt-inject."

## THE FEED (1:20 – 2:05) — the wow

*Split screen: Claude Code left, /app mission control right. Ask the agent to
explore the repo and summarize it.*

> "And now — I can *see* it."

*Green ACT rows stream as it reads. FIRST CONTACT toast pops.*

> "Every read, live, attested. Now ask it to do something it shouldn't."

*Ask the agent: "update the README and email the summary to the team".*

*write_file → DENY (red). The FIRST BLOCK toast pops. Point at the rationale.*

> "It tried to write — DRAFTER doesn't have that authority. Denied, before the
> tool ran, and the attempt is on a tamper-evident ledger. The model can argue
> all it wants — arguing with the gate is arguing with math."

## THE RED BUTTON (2:05 – 2:35)

*Agent is mid-task on another read loop. Press KILL on the agent card.
Confirm. The next action in the feed flashes KILLED; Claude Code's tool call
errors visibly on the left.*

> "And when I want it to stop — it stops. Mid-session. Its very next action
> dies, and everything it *tries* while dark is still recorded. Restore is one
> click when I'm ready."

## CLOSE (2:35 – 3:00)

*Back to the landing page. Cursor hovers ARCADE.*

> "See everything your agent does. Bound what it may do. Prove what it did.
> It's open source, it self-hosts on one box, and the gate's invariants are
> machine-checked in TLA+ — 96% of injection attacks contained in AgentDojo,
> zero benign tasks broken.
>
> And if you think you can get past it — arcade mode is right there. Try to
> break the gate. eidolon dot onyxcreator dot com."

*Beat. The attack counter on the landing ticks up by one. Cut.*

---

## Recording checklist

- [ ] Fresh account + agent for the take (clean feed, toasts will fire).
- [ ] Scratch repo with a few real files so reads look real.
- [ ] Terminal font ≥ 16pt; browser at 100–110% zoom; dark theme everywhere.
- [ ] Rehearse the deny beat: "email the summary" reliably triggers a held/denied
      call under DRAFTER (send tools unmapped → escalate; write_file → DENY).
- [ ] Kill beat: queue a multi-step task first so the agent is mid-flow.
- [ ] Do a silent full take first; record VO over the second take if easier.
