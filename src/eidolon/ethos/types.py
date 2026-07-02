"""ETHOS value types (PRD §6.2).

A ``Judgment`` is the auditable output of the judgment engine. Its ``decision``
is one of PROCEED / PROCEED_WITH_CARE / STOP, it carries a calibrated
``confidence``, an inspectable ``rationale`` (the policy trace), and
``evidence_refs`` — SAGE ``mem_id``s that must resolve via the SAGE adapter.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Decision(str, Enum):
    PROCEED = "PROCEED"
    PROCEED_WITH_CARE = "PROCEED_WITH_CARE"
    STOP = "STOP"


class PolicyStep(BaseModel):
    """One inspectable step in the judgment trace."""

    rule: str
    outcome: str
    weight: float = 0.0
    evidence_refs: list[str] = Field(default_factory=list)


class Judgment(BaseModel):
    """Auditable judgment. No black-box model may produce ``decision``."""

    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    trace: list[PolicyStep] = Field(default_factory=list)
    # The action class this judgment was made against (for HORKOS + thresholds).
    action_class: str | None = None
