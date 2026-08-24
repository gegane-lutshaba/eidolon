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

from eidolon.ethos.judgment.grounding import Embedder, relevance
from eidolon.ethos.types import Decision, Judgment, PolicyStep
from eidolon.profile.schema import DomainProfile
from eidolon.sage.port import Memory, SagePort
from eidolon.types import Action, Context

# Evidence-strength thresholds (transparent constants, not learned weights).
_STRONG_EVIDENCE = 1.5
_SOME_EVIDENCE = 0.6
# Relevance below this doesn't count a memory as supporting evidence.
_MIN_RELEVANCE = 0.12


class JudgmentEngine:
    """The auditable fidelity engine. Depends only on the SAGE port + profile.

    An optional :class:`Embedder` improves evidence *grounding* (relevance
    scoring) only; the decision remains a transparent threshold over the scores.
    """

    def __init__(self, sage: SagePort, *, recall_k: int = 8, embedder: Embedder | None = None) -> None:
        self._sage = sage
        self._recall_k = recall_k
        self._embedder = embedder

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
        """Confidence-weighted, relevance-scored evidence strength.

        Transparent and deterministic: for each memory, relevance ∈ [0,1] (a
        normalized-token Dice score, optionally blended with an embedding
        cosine) is multiplied by its SAGE confidence. Strength is their sum, with
        a small *consistency* bonus when several memories independently support
        the action (agreement is a real fidelity signal, and it reduces reliance
        on any single memory).
        """
        query = f"{action.description} {context.query}".strip()
        contributions: list[tuple[str, float]] = []
        total = 0.0
        for m in memories:
            rel = relevance(query, m.content, self._embedder)
            if rel < _MIN_RELEVANCE:
                continue
            contribution = m.confidence_score * rel
            total += contribution
            contributions.append((m.id, contribution))

        supporting = len(contributions)
        consistency = min(0.3, 0.1 * (supporting - 1)) if supporting > 1 else 0.0
        total *= 1.0 + consistency

        return total, PolicyStep(
            rule="evidence-grounding",
            outcome=(
                f"strength={total:.2f} from {supporting} memories "
                f"(consistency bonus {consistency:.2f})"
            ),
            weight=total,
            evidence_refs=[cid for cid, _ in contributions],
        )


def _calibrate(strength: float, *, ceiling: float) -> float:
    """Map raw evidence strength to a calibrated confidence, capped at ceiling.

    Saturating curve: confidence rises with evidence but never exceeds the
    band ceiling for its decision tier, keeping confidence honest.
    """
    saturated = 1.0 - pow(2.718281828, -max(strength, 0.0))
    return round(min(saturated, ceiling), 4)
