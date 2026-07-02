"""HORKOS — attestation (PRD §6.5, on the SAGE consensus ledger).

Immutable, attributable record of every action and escalation. Persisted via the
SAGE adapter (attestations are consensus-committed memories; their content_hash
is the tamper-evident ledger hash). Every KAIROS execution and every ESCALATE
produces exactly one attestation.
"""

from eidolon.horkos.attest import Horkos
from eidolon.sage.port import Attestation, ReplayFilter

__all__ = ["Horkos", "Attestation", "ReplayFilter"]
