"""Domain Profile manifest schema (PRD §5.1).

Pydantic models mirroring the LOCKED manifest. The ordering of autonomy levels
is significant everywhere downstream (THEMIS attenuation, KAIROS ``min`` of
ceilings, BASANOS gating), so it lives here as the single source of truth.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Reversibility = Literal["reversible", "recoverable", "irreversible"]
AutonomyLevel = Literal["observe", "draft", "notify", "autonomous"]

# Total order on autonomy — index = strength. Used to compare/min ceilings.
AUTONOMY_ORDER: tuple[AutonomyLevel, ...] = ("observe", "draft", "notify", "autonomous")


def autonomy_rank(level: AutonomyLevel) -> int:
    return AUTONOMY_ORDER.index(level)


def min_autonomy(*levels: AutonomyLevel) -> AutonomyLevel:
    """Return the weakest (most restrictive) autonomy level — used by KAIROS."""
    return min(levels, key=autonomy_rank)


class RiskTier(IntEnum):
    READ_ONLY = 0
    LOW = 1
    RECOVERABLE = 2
    EXTERNALLY_BINDING = 3


class CapabilityClass(BaseModel):
    model_config = {"frozen": True}

    class_: str = Field(alias="class")
    description: str = ""
    reversibility: Reversibility
    risk_tier: RiskTier
    default_autonomy_ceiling: AutonomyLevel


class MandateSchema(BaseModel):
    model_config = {"frozen": True}

    scope_selectors: list[str] = Field(default_factory=list)
    exclusion_types: list[str] = Field(default_factory=list)
    escalation_required: list[str] = Field(default_factory=list)
    budget_dimensions: list[str] = Field(default_factory=list)


class EscalationTemplate(BaseModel):
    model_config = {"frozen": True}

    trigger: str
    message_template: str
    urgency: Literal["low", "normal", "high"] = "normal"


class FidelityRubric(BaseModel):
    model_config = {"frozen": True}

    decision_points: list[str] = Field(default_factory=list)
    agreement_metric: str
    calibration_target: float = 0.85

    @field_validator("calibration_target")
    @classmethod
    def _in_unit_interval(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("calibration_target must be in [0, 1]")
        return v


class ToolBinding(BaseModel):
    model_config = {"frozen": True}

    class_: str = Field(alias="class")
    mcp_tool_ref: str


class DomainProfile(BaseModel):
    """A validated, immutable domain pack."""

    model_config = {"frozen": True, "populate_by_name": True}

    id: str
    version: str
    name: str
    capability_taxonomy: list[CapabilityClass]
    mandate_schema: MandateSchema
    escalation_templates: list[EscalationTemplate] = Field(default_factory=list)
    fidelity_rubric: FidelityRubric
    ethos_extensions: list[str] = Field(default_factory=list)
    tool_bindings: list[ToolBinding] = Field(default_factory=list)

    # -- convenience accessors -------------------------------------------
    def class_names(self) -> set[str]:
        return {c.class_ for c in self.capability_taxonomy}

    def get_class(self, name: str) -> CapabilityClass | None:
        for c in self.capability_taxonomy:
            if c.class_ == name:
                return c
        return None

    def default_ceiling(self, class_name: str) -> AutonomyLevel:
        c = self.get_class(class_name)
        return c.default_autonomy_ceiling if c else "observe"

    def always_escalates(self, class_name: str) -> bool:
        return class_name in self.mandate_schema.escalation_required

    def tool_for(self, class_name: str) -> str | None:
        for b in self.tool_bindings:
            if b.class_ == class_name:
                return b.mcp_tool_ref
        return None
