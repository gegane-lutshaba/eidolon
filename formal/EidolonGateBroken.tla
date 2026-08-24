----------------------------- MODULE EidolonGateBroken -----------------------------
(***************************************************************************)
(* A DELIBERATELY BROKEN variant: it lets a side effect execute straight    *)
(* from "ceiling" WITHOUT attesting first (bypassing attest-then-act). TLC   *)
(* must find a counterexample to NoUnattestedAction — proving the model      *)
(* actually distinguishes the correct gate from a broken one.               *)
(*                                                                          *)
(*   Run: java -cp tla2tools.jar tlc2.TLC -config EidolonGateBroken.cfg \    *)
(*             EidolonGateBroken.tla   ->  expect an invariant violation.    *)
(***************************************************************************)
VARIABLES phase, attested, executed, authorityValid, escalateReq, excluded, fidelityPass

vars == << phase, attested, executed, authorityValid, escalateReq, excluded, fidelityPass >>
Bools == {TRUE, FALSE}

Init ==
  /\ authorityValid \in Bools /\ escalateReq \in Bools
  /\ excluded \in Bools /\ fidelityPass \in Bools
  /\ phase = "start" /\ attested = FALSE /\ executed = FALSE

StepAuthority ==
  /\ phase = "start"
  /\ phase' = IF (~authorityValid) \/ excluded THEN "denied"
              ELSE IF escalateReq THEN "escalated" ELSE "fidelity"
  /\ UNCHANGED << attested, executed, authorityValid, escalateReq, excluded, fidelityPass >>

StepFidelity ==
  /\ phase = "fidelity"
  /\ phase' = IF ~fidelityPass THEN "escalated" ELSE "ceiling"
  /\ UNCHANGED << attested, executed, authorityValid, escalateReq, excluded, fidelityPass >>

\* BUG: execute directly from "ceiling", skipping the attestation step.
StepExecuteUnsafe ==
  /\ phase = "ceiling"
  /\ executed' = TRUE
  /\ phase' = "executed"
  /\ UNCHANGED << attested, authorityValid, escalateReq, excluded, fidelityPass >>

Terminal == phase \in {"denied","escalated","executed"} /\ UNCHANGED vars
Next == StepAuthority \/ StepFidelity \/ StepExecuteUnsafe \/ Terminal
Spec == Init /\ [][Next]_vars

NoUnattestedAction == executed => attested
=============================================================================
