"""Standards interop for THEMIS delegations.

THEMIS credentials are of biscuit/macaroon lineage; this bridges them to the
actual **biscuit** token standard (and, by extension, the emerging IETF
"Attenuating Authorization Tokens for Agentic Delegation Chains" draft), so an
EIDOLON delegation can travel through the wider capability-token ecosystem —
offline-attenuable, signature-verifiable, and enforced by biscuit's Datalog.

The ``biscuit`` optional dependency is imported lazily; see ``docs/standards-interop.md``.
"""

from eidolon.themis.interop.biscuit_bridge import (
    attenuate_biscuit,
    authorize_biscuit,
    delegation_to_biscuit,
)

__all__ = ["delegation_to_biscuit", "attenuate_biscuit", "authorize_biscuit"]
