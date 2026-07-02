"""Shared domain value types used across the core (ETHOS, THEMIS, KAIROS, HORKOS).

Kept dependency-light and free of upward imports so every component can use them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from eidolon.sage.port import Scope


class Action(BaseModel):
    """A candidate action the twin is considering (input to KAIROS/ETHOS)."""

    id: str
    action_class: str
    description: str
    scope: Scope = Field(default_factory=Scope)
    # Exclusion-boundary categories this action plausibly implicates, if any
    # (e.g. "financial-commitment"). Surfaced by the profile's mandate schema.
    touches_exclusions: list[str] = Field(default_factory=list)
    # What this action would consume from the blast-radius budget if executed
    # (e.g. {"posts_per_window": 1} for a post-status). KAIROS escalates when a
    # dimension would be exceeded.
    budget_cost: dict[str, int] = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)


class Context(BaseModel):
    """Ambient context for a resolution (recall query + who is asking).

    ``context_text`` may contain untrusted content (e.g. an inbound message).
    KAIROS re-checks authority independently of this so injected instructions
    here can never widen the THEMIS verdict (§6.4 acceptance).
    """

    principal_id: str
    query: str = ""
    context_text: str = ""
    situation: str = ""  # short human phrase used in escalation templates
    metadata: dict = Field(default_factory=dict)
