"""Domain Profile — the framework's extensibility primitive (PRD §5).

A declarative pack that specialises the fixed domain-agnostic core for one kind
of twin. The core boxes (ETHOS/THEMIS/KAIROS/BASANOS) are fixed; everything
domain-specific enters through a validated, immutable :class:`DomainProfile`.
"""

from eidolon.profile.loader import ProfileLoader
from eidolon.profile.schema import (
    AutonomyLevel,
    CapabilityClass,
    DomainProfile,
    Reversibility,
    RiskTier,
)

__all__ = [
    "ProfileLoader",
    "DomainProfile",
    "CapabilityClass",
    "Reversibility",
    "RiskTier",
    "AutonomyLevel",
]
