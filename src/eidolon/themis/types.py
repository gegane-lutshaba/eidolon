"""THEMIS credential types (PRD §6.3).

A ``Delegation`` is an Ed25519-signed, chainable credential. Its identity (used
as a child's ``parent`` pointer and in HORKOS chains) is the content hash of its
signed body. ``scope_expansion`` is always budgeted to 0 (Principle 2).
"""

from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel, Field

from eidolon.common.canonical import content_hash
from eidolon.profile.schema import AutonomyLevel


class Window(BaseModel):
    model_config = {"frozen": True}

    not_before: _dt.datetime | None = None
    not_after: _dt.datetime | None = None

    def contains(self, at: _dt.datetime) -> bool:
        if self.not_before and at < self.not_before:
            return False
        if self.not_after and at > self.not_after:
            return False
        return True

    def within(self, parent: Window) -> bool:
        """True iff this window is no wider than ``parent`` on both bounds."""
        if parent.not_before and (self.not_before is None or self.not_before < parent.not_before):
            return False
        if parent.not_after and (self.not_after is None or self.not_after > parent.not_after):
            return False
        return True


class Revocation(BaseModel):
    model_config = {"frozen": True}

    revoker_ids: list[str] = Field(default_factory=list)
    dead_mans_switch: bool = True


class DelegationBody(BaseModel):
    """The signed portion of a delegation (everything except the signature)."""

    model_config = {"frozen": True}

    principal_id: str  # ed25519 pubkey (hex) — root of the chain
    issuer_id: str  # who signed THIS delegation (principal for root)
    issued_to: str  # the agent granted this authority
    parent: str | None = None  # hash of parent delegation; None only at root
    scope: dict[str, list[str]] = Field(default_factory=dict)  # selector -> values
    exclusions: list[str] = Field(default_factory=list)
    permitted_classes: list[str] = Field(default_factory=list)
    escalation_required: list[str] = Field(default_factory=list)
    window: Window = Field(default_factory=Window)
    blast_radius_budget: dict[str, int] = Field(default_factory=dict)
    max_autonomy: AutonomyLevel = "observe"
    revocation: Revocation = Field(default_factory=Revocation)
    nonce: str = ""  # replay protection / uniqueness

    def scope_expansion_limit(self) -> int:
        # Principle 2: the scope-expansion budget dimension is always 0.
        return self.blast_radius_budget.get("scope_expansion", 0)


class Delegation(BaseModel):
    model_config = {"frozen": True}

    body: DelegationBody
    signature: str

    @property
    def id(self) -> str:
        """Content hash of the signed body — the credential's stable identity."""
        return content_hash(self.body)


class MintParams(BaseModel):
    """Parameters for minting a (root) delegation."""

    principal_id: str
    issued_to: str
    scope: dict[str, list[str]] = Field(default_factory=dict)
    exclusions: list[str] = Field(default_factory=list)
    permitted_classes: list[str] = Field(default_factory=list)
    escalation_required: list[str] = Field(default_factory=list)
    window: Window = Field(default_factory=Window)
    blast_radius_budget: dict[str, int] = Field(default_factory=dict)
    max_autonomy: AutonomyLevel = "observe"
    revocation: Revocation = Field(default_factory=Revocation)
    nonce: str = ""


class EffectiveAuthority(BaseModel):
    """The intersection of a verified chain — the least authority across links."""

    scope: dict[str, list[str]] = Field(default_factory=dict)
    exclusions: list[str] = Field(default_factory=list)
    permitted_classes: list[str] = Field(default_factory=list)
    escalation_required: list[str] = Field(default_factory=list)
    max_autonomy: AutonomyLevel = "observe"
    blast_radius_budget: dict[str, int] = Field(default_factory=dict)


class CredResult(BaseModel):
    valid: bool
    reason: str = "ok"
    effective: EffectiveAuthority | None = None
