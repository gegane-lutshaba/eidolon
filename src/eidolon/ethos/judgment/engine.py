"""Structured decision-policy evaluator (PRD §6.2, §6.3 P1.2.1).

Given an action, ambient context, and SAGE-recalled memories, produce an
auditable :class:`Judgment`. The policy is a transparent, deterministic scoring
function — NOT a model — so ``decision`` and ``confidence`` are always
inspectable and every judgment carries resolvable ``evidence_refs``.

Policy (in order):
1. **Exclusion guard.** If the action implicates any hard-boundary exclusion the
   principal reserves for themselves, decide STOP (would not act) — the twin
   should hand this back.
2. **Evidence grounding.** Recall memories relevant to the action; measure
   evidence strength from their count and SAGE confidence scores.
3. **Decision + calibration.** Strong grounding -> PROCEED; partial -> PROCEED_
   WITH_CARE; thin/absent -> STOP. Confidence is a calibrated function of
   evidence strength, deliberately damped when grounding is weak.
"""

from __future__ import annotations

from eidolon.ethos.types import Decision, Judgment, PolicyStep
from eidolon.profile.schema import DomainProfile
from eidolon.sage.port import Memory, SagePort
from eidolon.types import Action, Context

# Evidence-strength thresholds (transparent constants, not learned weights).
_STRONG_EVIDENCE = 1.5
_SOME_EVIDENCE = 0.6


class JudgmentEngine:
    """The auditable fidelity engine. Depends only on the SAGE port + profile."""

    def __init__(self, sage: SagePort, *, recall_k: int = 8) -> None:
        self._sage = sage
        self._recall_k = recall_k

    def evaluate(
        self,
        action: Action,
        context: Context,
        memories: list[Memory] | None,
        profile: DomainProfile,
    ) -> Judgment:
        trace: list[PolicyStep] = []

        # Ground in memory. Callers may pass pre-fetched memories (e.g. KAIROS);
        # otherwise recall here so the judgment is always evidence-backed.
        if memories is None:
            query = context.query or action.description
            memories = self._sage.recall(context.principal_id, action.scope, query, self._recall_k)
        evidence_refs = [m.id for m in memories]

        # -- Rule 1: exclusion guard --------------------------------------
        exclusions = set(profile.mandate_schema.exclusion_types)
        hit = [e for e in action.touches_exclusions if e in exclusions]
        if hit:
            trace.append(
                PolicyStep(
                    rule="exclusion-guard",
                    outcome=f"STOP: touches reserved boundary {hit}",
                    weight=-1.0,
                )
            )
            return Judgment(
                decision=Decision.STOP,
                confidence=0.98,  # high confidence the principal would NOT act
                rationale=(
                    f"Action implicates hard-boundary exclusion(s) {hit}; the "
                    f"principal reserves these decisions. Handing back."
                ),
                evidence_refs=evidence_refs,
                trace=trace,
                action_class=action.action_class,
            )

        # -- Rule 2: evidence grounding -----------------------------------
        strength, ev_trace = self._evidence_strength(action, context, memories)
        trace.append(ev_trace)

        # -- Rule 3: decision + calibration -------------------------------
        if strength >= _STRONG_EVIDENCE:
            decision = Decision.PROCEED
            confidence = _calibrate(strength, ceiling=0.95)
            rationale = "Strong precedent in recalled memory for how the principal handles this."
        elif strength >= _SOME_EVIDENCE:
            decision = Decision.PROCEED_WITH_CARE
            confidence = _calibrate(strength, ceiling=0.75)
            rationale = "Partial precedent; proceed only in a reviewable (draft) form."
        else:
            decision = Decision.STOP
            confidence = _calibrate(strength, ceiling=0.5)
            rationale = "Insufficient grounding to act as the principal would; escalating."

        trace.append(
            PolicyStep(
                rule="decision",
                outcome=f"{decision.value} @ confidence={confidence:.2f}",
                weight=strength,
                evidence_refs=evidence_refs,
            )
        )
        return Judgment(
            decision=decision,
            confidence=confidence,
            rationale=rationale,
            evidence_refs=evidence_refs,
            trace=trace,
            action_class=action.action_class,
        )

    # -- helpers ----------------------------------------------------------
    def _evidence_strength(
        self, action: Action, context: Context, memories: list[Memory]
    ) -> tuple[float, PolicyStep]:
        """Sum SAGE confidence over memories that lexically overlap the action.

        Transparent and deterministic: strength is the confidence-weighted count
        of relevant memories. Higher-confidence, on-topic memories count more.
        """
        terms = _terms(action.description) | _terms(context.query)
        total = 0.0
        contributing: list[str] = []
        for m in memories:
            overlap = len(terms & _terms(m.content))
            if overlap == 0:
                continue
            contribution = m.confidence_score * min(overlap, 3) / 3.0
            total += contribution
            contributing.append(m.id)
        return total, PolicyStep(
            rule="evidence-grounding",
            outcome=f"strength={total:.2f} from {len(contributing)} memories",
            weight=total,
            evidence_refs=contributing,
        )


def _calibrate(strength: float, *, ceiling: float) -> float:
    """Map raw evidence strength to a calibrated confidence, capped at ceiling.

    Saturating curve: confidence rises with evidence but never exceeds the
    band ceiling for its decision tier, keeping confidence honest.
    """
    saturated = 1.0 - pow(2.718281828, -max(strength, 0.0))
    return round(min(saturated, ceiling), 4)


def _terms(text: str) -> set[str]:
    return {t for t in text.lower().replace(",", " ").replace(".", " ").split() if len(t) > 2}
