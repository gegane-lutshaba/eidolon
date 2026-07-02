"""Skill synthesis — learn a procedure from a completed session (PRD §2.2 v2).

Hermes-style: after the twin completes a non-trivial task (several authorized
acting steps), capture the successful path as a reusable skill. Synthesis is
STRUCTURAL and inspectable — it records which capability classes ran, in what
order, with what scope; it invents no authority. A style engine may name/describe
the skill, but the plan itself is derived deterministically.

Only steps that were actually *authorized to act* (DRAFT / NOTIFY_ACT /
AUTONOMOUS_ACT) are captured. Denied or escalated steps are never part of a
learned skill — a skill can only encode what the twin was permitted to do.
"""

from __future__ import annotations

from eidolon.common.errors import ProfileInvalid
from eidolon.kairos.types import Decision, DecisionLevel
from eidolon.profile.schema import DomainProfile
from eidolon.skills.types import Skill, SkillStep
from eidolon.types import Action

# Levels that represent an authorized step worth capturing into a skill.
_CAPTURABLE = {DecisionLevel.DRAFT, DecisionLevel.NOTIFY_ACT, DecisionLevel.AUTONOMOUS_ACT}

# Hermes-style default: capture a skill only after a non-trivial task.
DEFAULT_MIN_STEPS = 3


def should_synthesize(
    session: list[tuple[Action, Decision]], *, min_steps: int = DEFAULT_MIN_STEPS
) -> bool:
    """True if the session has enough authorized acting steps to be worth saving."""
    acting = sum(1 for _, d in session if d.level in _CAPTURABLE)
    return acting >= min_steps


def synthesize(
    name: str,
    description: str,
    principal_id: str,
    profile: DomainProfile,
    session: list[tuple[Action, Decision]],
    *,
    source_refs: list[str] | None = None,
) -> Skill:
    """Build a :class:`Skill` from the authorized acting steps of a session.

    Raises :class:`ProfileInvalid` if any captured step references a class not in
    the profile taxonomy (a skill can only reference real capability classes).
    """
    classes = profile.class_names()
    steps: list[SkillStep] = []
    refs = list(source_refs or [])

    for action, decision in session:
        if decision.level not in _CAPTURABLE:
            continue
        if action.action_class not in classes:
            raise ProfileInvalid(
                f"skill step references class {action.action_class!r} not in "
                f"profile {profile.id!r}"
            )
        steps.append(
            SkillStep(
                action_class=action.action_class,
                description=action.description,
                scope=action.scope,
                budget_cost=action.budget_cost,
            )
        )
        if decision.attestation_hash:
            refs.append(decision.attestation_hash)

    if not steps:
        raise ProfileInvalid("cannot synthesize a skill with no authorized steps")

    return Skill(
        name=name,
        description=description,
        principal_id=principal_id,
        profile_id=profile.id,
        steps=steps,
        source_refs=refs,
    )
