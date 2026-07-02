"""Skill executor — replay a skill, subordinate to KAIROS (PRD §2.2 v2).

Each step is turned into a concrete :class:`Action` (with ``{param}``
substitution) and resolved through the KAIROS gate exactly like any other
candidate action: THEMIS authority, ETHOS fidelity, BASANOS ceiling, and
attest-then-act. The executor NEVER pre-authorizes or batches — it holds no
credential of its own and cannot widen authority.

If a step is denied or escalated, the run STOPS there and hands back: a learned
skill can propose steps, but the gate decides each one afresh. This is what
makes skills safe — a skill recorded under broad authority yields nothing when
replayed under a narrower (or revoked) delegation.
"""

from __future__ import annotations

from eidolon.kairos.gate import Kairos
from eidolon.kairos.types import DecisionLevel
from eidolon.sage.port import Scope
from eidolon.skills.types import Skill, SkillRun, StepOutcome
from eidolon.types import Action, Context

_HALTING = {DecisionLevel.DENY, DecisionLevel.ESCALATE}


class SkillExecutor:
    def __init__(self, kairos: Kairos) -> None:
        self._kairos = kairos

    def run(
        self,
        skill: Skill,
        context: Context,
        chain,  # list[Delegation]
        certificates=None,
        *,
        params: dict[str, str] | None = None,
        integrity_certificate=None,
    ) -> SkillRun:
        params = params or {}
        run = SkillRun(skill_id=skill.id, principal_id=context.principal_id)

        for i, step in enumerate(skill.steps):
            action = Action(
                id=f"{skill.id}-{i}",
                action_class=step.action_class,
                description=_subst(step.description, params),
                scope=_subst_scope(step.scope, params),
                budget_cost=dict(step.budget_cost),
            )
            decision = self._kairos.resolve(
                action, context, chain, certificates, integrity_certificate
            )
            run.outcomes.append(
                StepOutcome(
                    index=i,
                    action_class=step.action_class,
                    level=decision.level.value,
                    attestation_hash=decision.attestation_hash,
                    output=decision.output,
                )
            )
            if decision.level in _HALTING:
                run.stopped_at = i
                run.stop_reason = f"step {i} ({step.action_class}) -> {decision.level.value}"
                return run

        run.completed = True
        return run


def _subst(text: str, params: dict[str, str]) -> str:
    for key, val in params.items():
        text = text.replace("{" + key + "}", val)
    return text


def _subst_scope(scope: Scope, params: dict[str, str]) -> Scope:
    return Scope(
        selectors={
            stype: [_subst(v, params) for v in vals]
            for stype, vals in scope.selectors.items()
        }
    )
