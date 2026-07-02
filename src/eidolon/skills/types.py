"""Skill value types (PRD §2.2 v2).

A :class:`Skill` carries NO authority and NO decision — only a parameterized
plan. Its identity is the content hash of its steps, so an altered skill is a
different skill (tamper-evident, like every other EIDOLON record).
"""

from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel, Field

from eidolon.common.canonical import content_hash
from eidolon.sage.port import Scope


class SkillStep(BaseModel):
    """One planned step. References a capability class + a parameterized action.

    Placeholders of the form ``{name}`` in ``description`` and in scope selector
    values are substituted from run-time params. A step never carries a
    credential — authority is resolved fresh at execution.
    """

    model_config = {"frozen": True}

    action_class: str
    description: str
    scope: Scope = Field(default_factory=Scope)
    budget_cost: dict[str, int] = Field(default_factory=dict)


class Skill(BaseModel):
    """A learned, reusable procedure (procedural memory)."""

    model_config = {"frozen": True}

    name: str
    description: str
    principal_id: str
    profile_id: str
    steps: list[SkillStep]
    # Attestation hashes of the session this skill was learned from (provenance).
    source_refs: list[str] = Field(default_factory=list)
    created_at: _dt.datetime | None = None

    @property
    def id(self) -> str:
        return "skill-" + content_hash(
            {
                "principal_id": self.principal_id,
                "profile_id": self.profile_id,
                "steps": [s.model_dump(mode="json") for s in self.steps],
            }
        )[:16]

    def classes(self) -> list[str]:
        return [s.action_class for s in self.steps]


class StepOutcome(BaseModel):
    """The result of resolving one skill step through KAIROS."""

    index: int
    action_class: str
    level: str  # KAIROS DecisionLevel
    attestation_hash: str | None = None
    output: str | None = None


class SkillRun(BaseModel):
    """The audit trail of replaying a skill — subordinate to KAIROS."""

    skill_id: str
    principal_id: str
    outcomes: list[StepOutcome] = Field(default_factory=list)
    completed: bool = False
    # Index at which the run stopped (a step that was denied/escalated), if any.
    stopped_at: int | None = None
    stop_reason: str | None = None
