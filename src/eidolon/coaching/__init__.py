"""Aspirational-self / coaching layer (PRD §2.2, §12 — v2).

Reads ETHOS version diffs and the HORKOS attestation history to coach the
principal toward who they *aspire* to be — separate from the operating model
(who they currently are). It is **fully decoupled**: nothing in the decision
path (ETHOS judgment, THEMIS, KAIROS) imports this package, and running the coach
changes zero live decisions. The coach only observes and advises; it never writes
to the operating model or to judgment-visible memory.
"""

from eidolon.coaching.coach import Coach
from eidolon.coaching.types import (
    Aspiration,
    BehaviorSummary,
    ClassTarget,
    CoachingNote,
    CoachingReport,
    DriftReport,
)

__all__ = [
    "Coach",
    "Aspiration",
    "ClassTarget",
    "BehaviorSummary",
    "DriftReport",
    "CoachingNote",
    "CoachingReport",
]
