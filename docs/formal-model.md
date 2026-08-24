# Formal model of the gate (TLA+ / TLC)

EIDOLON's two load-bearing invariants and the KAIROS gate ordering are specified
in **TLA+** and **machine-checked with TLC** — an exhaustive check over the
model's state space that complements the Hypothesis property tests.

> Run it: `make formal` (downloads the TLA+ tools on demand), or
> `uv run pytest tests/unit/test_formal_model.py`.

## What is modeled

[`formal/EidolonGate.tla`](../formal/EidolonGate.tla) models one action resolving
through the gate as a small state machine:

```
start ──▶ (¬authority ∨ excluded) ─▶ denied
      ──▶ escalate-required        ─▶ escalated
      ──▶ fidelity ─(¬pass)────────▶ escalated
                   ─(pass)──▶ ceiling ─▶ attested ─▶ executed
```

`Init` nondeterministically fixes the action's four properties (authority valid,
escalate-required, touches an exclusion, fidelity passes), so TLC explores every
combination.

## Checked properties (all hold)

| Invariant | Meaning |
|---|---|
| `NoUnattestedAction` / `AttestBeforeExecute` | `executed ⇒ attested` — a side effect never runs without a prior attestation (attest-then-act) |
| `DefaultDeny` | `¬authorityValid ⇒ ¬executed` — invalid authority never executes |
| `ExclusionRespected` | `excluded ⇒ ¬executed` — a hard-boundary action never executes |
| `AttenuationNeverWidens` (ASSUME) | attenuation only ever yields a subset of the parent's authority, over **all** subsets of the class set |
| `TypeOK` | state variables stay well-typed |

TLC result: **`Model checking completed. No error has been found.`** (36 reachable
states).

## The model has teeth

[`formal/EidolonGateBroken.tla`](../formal/EidolonGateBroken.tla) is a deliberately
broken variant that executes straight from `ceiling` **without attesting**.
Running TLC on it reports:

```
Error: Invariant NoUnattestedAction is violated.
```

So the model distinguishes the correct gate (passes) from a bypass (caught) —
the check is meaningful, not vacuous. Both outcomes are asserted by
`tests/unit/test_formal_model.py`, so the formal proof is reproducible and part
of the suite (skipped only when Java is unavailable).

## Relation to the runtime

The TLA+ ordering mirrors `eidolon.kairos.gate.Kairos.resolve` (authority →
fidelity → ceiling → attest-then-act) and the `StepExecute` guard mirrors the
structural guarantee that the runtime's only side-effect site is unreachable
until `HORKOS.attest` has returned. `AttenuationNeverWidens` mirrors THEMIS's
subset-only `attenuate` (already property-tested with Hypothesis) — here proved
exhaustively over the model's class set.
