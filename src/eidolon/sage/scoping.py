"""Map EIDOLON scoping onto SAGE's Organization -> Department -> Domain -> Agent
model with clearance levels (PRD §6.1 Notes).

Rules enforced here:
- Each principal is its own SAGE Organization (single-tenant ownership, §7).
- A recall/write Scope's selectors become SAGE domain tags.
- Access controls are set BEFORE any write — SAGE cannot retroactively restrict.
- EIDOLON clearance needs are clamped onto SAGE's actual range (observed 0..2).
"""

from __future__ import annotations

import hashlib

from eidolon.sage.port import Scope

# SAGE's current SDK exposes clearance 0..2 (PUBLIC, INTERNAL, CONFIDENTIAL).
# The PRD references 0..4; we clamp EIDOLON's requests to the live range so the
# adapter never asks SAGE for a clearance it cannot represent.
SAGE_MIN_CLEARANCE = 0
SAGE_MAX_CLEARANCE = 2


def clamp_clearance(level: int) -> int:
    return max(SAGE_MIN_CLEARANCE, min(SAGE_MAX_CLEARANCE, level))


def org_name_for_principal(principal_id: str) -> str:
    """Deterministic, collision-resistant org name for a principal.

    Principals are keyed by Ed25519 pubkey (possibly long/hex); we derive a
    stable short org handle so the same principal always maps to the same org.
    """
    digest = hashlib.sha256(principal_id.encode("utf-8")).hexdigest()[:16]
    return f"eidolon-principal-{digest}"


def domain_tags(scope: Scope) -> list[str]:
    """SAGE domain tags for a scope. Empty scope -> the principal's base domain."""
    tags = scope.domains()
    return tags or ["base"]


def _sanitize(name: str) -> str:
    """SAGE domain names are flat lowercase tokens (e.g. 'pwn_heap')."""
    return "".join(ch if ch.isalnum() else "_" for ch in name.lower())


def principal_domain(principal_id: str) -> str:
    """One SAGE domain per principal.

    Live cross-principal isolation is enforced by writing each principal's
    observations into a distinct, principal-derived domain (verified against a
    live node). Intra-principal scope narrowing is carried on tags. This is why
    a recall scoped to principal B — which only ever queries B's domain — can
    never observe principal A's memories.
    """
    return _sanitize(org_name_for_principal(principal_id))


def attestation_domain(principal_id: str, base: str = "attestations") -> str:
    """Per-principal ledger domain for HORKOS attestations."""
    return _sanitize(f"{org_name_for_principal(principal_id)}_{base}")


def scope_tags(scope: Scope, provenance: str | None = None) -> list[str]:
    """Tags carried on a write: scope selectors + optional provenance marker."""
    tags = list(scope.domains())
    if provenance:
        tags.append(f"provenance:{provenance}")
    return tags
