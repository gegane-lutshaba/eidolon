"""KAIROS value types (PRD §6.4)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from eidolon.profile.schema import AutonomyLevel


class DecisionLevel(str, Enum):
    DENY = "DENY"
    ESCALATE = "ESCALATE"
    DRAFT = "DRAFT"
    NOTIFY_ACT = "NOTIFY_ACT"
    AUTONOMOUS_ACT = "AUTONOMOUS_ACT"


# Map an effective autonomy level onto the actionable gate outcome. ``observe``
# means the twin is not cleared to act on this class, so it hands the decision
# back (ESCALATE) rather than executing.
_AUTONOMY_TO_LEVEL: dict[AutonomyLevel, DecisionLevel] = {
    "observe": DecisionLevel.ESCALATE,
    "draft": DecisionLevel.DRAFT,
    "notify": DecisionLevel.NOTIFY_ACT,
    "autonomous": DecisionLevel.AUTONOMOUS_ACT,
}


def level_for_autonomy(level: AutonomyLevel) -> DecisionLevel:
    return _AUTONOMY_TO_LEVEL[level]


class Decision(BaseModel):
    level: DecisionLevel
    rationale: str
    attestation_hash: str | None = None
    # Populated when the gate produced output the caller can use.
    output: str | None = None  # draft text or escalation message
    action_class: str | None = None


class BudgetLedger:
    """Tracks blast-radius consumption per principal per dimension.

    v1 keeps a flat counter (windowing deferred). ``would_exceed`` is checked in
    KAIROS step 1; ``consume`` is called only after a successful attest-then-act.
    """

    def __init__(self) -> None:
        self._consumed: dict[tuple[str, str], int] = {}

    def consumed(self, principal_id: str, dim: str) -> int:
        return self._consumed.get((principal_id, dim), 0)

    def would_exceed(self, principal_id: str, cost: dict[str, int], limits: dict[str, int]) -> str | None:
        for dim, amount in cost.items():
            limit = limits.get(dim)
            if limit is None:
                continue
            if self.consumed(principal_id, dim) + amount > limit:
                return dim
        return None

    def consume(self, principal_id: str, cost: dict[str, int]) -> None:
        for dim, amount in cost.items():
            self._consumed[(principal_id, dim)] = self.consumed(principal_id, dim) + amount
