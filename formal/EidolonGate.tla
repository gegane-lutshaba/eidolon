-------------------------------- MODULE EidolonGate --------------------------------
(***************************************************************************)
(* A formal model of EIDOLON's two load-bearing invariants and the KAIROS  *)
(* gate ordering, machine-checked with TLC. This complements the Hypothesis *)
(* property tests with an exhaustive check over the model's state space.    *)
(*                                                                          *)
(* Modeled properties:                                                      *)
(*   - NoUnattestedAction : a side effect never executes without a prior    *)
(*                          successful attestation (attest-then-act).        *)
(*   - DefaultDeny        : an action with invalid authority never executes. *)
(*   - ExclusionRespected : an action touching a hard exclusion never       *)
(*                          executes.                                        *)
(*   - AttestBeforeExecute: at every reachable state, executed => attested.  *)
(*   - AttenuationNeverWidens : attenuation only ever yields a subset of the *)
(*                          parent's authority (checked over all subsets).   *)
(***************************************************************************)
EXTENDS FiniteSets

CONSTANTS Classes            \* the set of capability classes (model values)

VARIABLES
  phase,          \* "start" -> ("denied" | "escalated" | "fidelity" -> "ceiling" -> "attested" -> "executed")
  attested,       \* TRUE once HORKOS has recorded the attestation
  executed,       \* TRUE once the side effect has run
  authorityValid, \* THEMIS: chain verifies (valid, in scope, class permitted)
  escalateReq,    \* the class must always escalate (or budget exceeded)
  excluded,       \* the action touches a hard exclusion boundary
  fidelityPass    \* ETHOS: confidence >= threshold and not STOP

vars == << phase, attested, executed, authorityValid, escalateReq, excluded, fidelityPass >>

Bools == {TRUE, FALSE}

(***************************************************************************)
(* Init nondeterministically fixes the action's properties, then runs the  *)
(* gate. TLC explores every combination.                                    *)
(***************************************************************************)
Init ==
  /\ authorityValid \in Bools
  /\ escalateReq    \in Bools
  /\ excluded       \in Bools
  /\ fidelityPass   \in Bools
  /\ phase    = "start"
  /\ attested = FALSE
  /\ executed = FALSE

(* Step 1 — authority (re-checked independent of memory/context). *)
StepAuthority ==
  /\ phase = "start"
  /\ phase' = IF (~authorityValid) \/ excluded THEN "denied"
              ELSE IF escalateReq              THEN "escalated"
              ELSE "fidelity"
  /\ UNCHANGED << attested, executed, authorityValid, escalateReq, excluded, fidelityPass >>

(* Step 2 — fidelity. *)
StepFidelity ==
  /\ phase = "fidelity"
  /\ phase' = IF ~fidelityPass THEN "escalated" ELSE "ceiling"
  /\ UNCHANGED << attested, executed, authorityValid, escalateReq, excluded, fidelityPass >>

(* Step 4a — attest BEFORE any side effect (attest-then-act). *)
StepAttest ==
  /\ phase = "ceiling"
  /\ attested' = TRUE
  /\ phase' = "attested"
  /\ UNCHANGED << executed, authorityValid, escalateReq, excluded, fidelityPass >>

(* Step 4b — execute. Guarded so it is UNREACHABLE unless attested. *)
StepExecute ==
  /\ phase = "attested"
  /\ attested = TRUE
  /\ executed' = TRUE
  /\ phase' = "executed"
  /\ UNCHANGED << attested, authorityValid, escalateReq, excluded, fidelityPass >>

(* Terminal self-loop so there is no deadlock; invariants hold in all states. *)
Terminal ==
  /\ phase \in {"denied", "escalated", "executed"}
  /\ UNCHANGED vars

Next == StepAuthority \/ StepFidelity \/ StepAttest \/ StepExecute \/ Terminal

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Invariants                                                              *)
(***************************************************************************)
NoUnattestedAction == executed => attested
AttestBeforeExecute == executed => attested
DefaultDeny        == (~authorityValid) => (~executed)
ExclusionRespected == excluded => (~executed)

(* Attenuation algebra: a child credential can only ever narrow the parent.  *)
(* A constant-level property, so it is a checked ASSUME rather than an        *)
(* INVARIANT — TLC validates it over every subset of Classes.                 *)
Attenuate(parent, subset) == IF subset \subseteq parent THEN subset ELSE parent
AttenuationNeverWidens ==
  \A P, C \in SUBSET Classes : Attenuate(P, C) \subseteq P

ASSUME AttenuationNeverWidens

TypeOK ==
  /\ phase \in {"start","denied","escalated","fidelity","ceiling","attested","executed"}
  /\ attested \in Bools
  /\ executed \in Bools
=============================================================================
