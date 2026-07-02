"""Coaching value types (PRD §12 v2).

These are advisory records only. They are never consumed by the operating model
— by construction, no decision-path component imports this module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClassTarget(BaseModel):
    """A measurable aspiration for one capability class."""

    model_config = {"frozen": True}

    action_class: str
    # Desired fraction of decisions the principal wants escalated (0..1).
    target_escalation_rate: float | None = None
    # Minimum confidence the principal aspires to have before acting.
    min_confidence_to_act: float | None = None
    note: str = ""


class Aspiration(BaseModel):
    """Who the principal wants to become — declared, decoupled from behavior."""

    principal_id: str
    values: list[str] = Field(default_factory=list)  # free-text principles
    targets: list[ClassTarget] = Field(default_factory=list)

    def target_for(self, action_class: str) -> ClassTarget | None:
        for t in self.targets:
            if t.action_class == action_class:
                return t
        return None


class BehaviorSummary(BaseModel):
    """Observed behavior for one class, derived from the attestation ledger."""

    model_config = {"frozen": True}

    action_class: str
    decisions: int
    escalations: int
    acted: int  # reached an acting level (draft/notify/autonomous)
    avg_confidence: float | None = None

    @property
    def escalation_rate(self) -> float:
        return self.escalations / self.decisions if self.decisions else 0.0


class DriftReport(BaseModel):
    """Policy drift between two ETHOS snapshots (from ETHOS version diffs)."""

    model_config = {"frozen": True}

    version_from: str
    version_to: str
    changed: dict = Field(default_factory=dict)

    @property
    def drifted(self) -> bool:
        return bool(self.changed)


class CoachingNote(BaseModel):
    model_config = {"frozen": True}

    topic: str
    observation: str
    suggestion: str
    severity: Literal["info", "nudge", "flag"] = "nudge"


class CoachingReport(BaseModel):
    """The coach's read-only output for a principal."""

    model_config = {"frozen": True}

    principal_id: str
    notes: list[CoachingNote] = Field(default_factory=list)
    behavior: list[BehaviorSummary] = Field(default_factory=list)
    drift: DriftReport | None = None
