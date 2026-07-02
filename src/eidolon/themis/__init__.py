"""THEMIS — authority engine (PRD §6.3).

Mint, verify, attenuate, and revoke delegation credentials. Credentials are of
biscuit/macaroon lineage: Ed25519-signed, chained parent->child, offline
verifiable, and attenuable subset-only. Authority attenuates, never widens —
including twin->sub-agent delegation (Principle 2).
"""

from eidolon.themis.engine import Themis
from eidolon.themis.revocation_store import RevocationStore
from eidolon.themis.types import (
    CredResult,
    Delegation,
    EffectiveAuthority,
    MintParams,
    Window,
)

__all__ = [
    "Themis",
    "Delegation",
    "MintParams",
    "Window",
    "CredResult",
    "EffectiveAuthority",
    "RevocationStore",
]
