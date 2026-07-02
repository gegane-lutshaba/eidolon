"""KAIROS — action gate (PRD §6.4).

The single choke point. Every candidate action is resolved here, in the LOCKED
order (authority -> fidelity -> autonomy ceiling -> attest-then-act). No code
path reaches a side effect without a prior successful HORKOS attestation.
"""

from eidolon.kairos.gate import Kairos
from eidolon.kairos.types import BudgetLedger, Decision, DecisionLevel

__all__ = ["Kairos", "Decision", "DecisionLevel", "BudgetLedger"]
