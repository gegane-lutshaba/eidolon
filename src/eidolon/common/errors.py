"""EIDOLON error taxonomy.

The two load-bearing invariants (PRD §0) have dedicated exception types so that
any accidental bypass surfaces loudly rather than silently degrading to
"allowed".
"""

from __future__ import annotations


class EidolonError(Exception):
    """Base class for all EIDOLON errors."""


class DefaultDeny(EidolonError):
    """Invariant 1: authority not explicitly granted is denied."""


class ScopeViolation(DefaultDeny):
    """A requested action falls outside the delegation's scope/exclusions."""


class AttenuationError(EidolonError):
    """A child credential attempted to widen its parent's authority."""


class CredentialInvalid(DefaultDeny):
    """A delegation chain failed verification (expired, revoked, broken)."""


class AttestationFailed(EidolonError):
    """Invariant 2: an attestation could not be written; the action must abort."""


class ConsentMissing(EidolonError):
    """Capture attempted without a valid, principal-owned ConsentGrant."""


class ProfileInvalid(EidolonError):
    """A Domain Profile manifest failed schema or invariant validation."""


class IsolationViolation(EidolonError):
    """The style engine attempted to influence a judgment (§6.2 boundary)."""


class SageBackendError(EidolonError):
    """The SAGE substrate rejected or failed an operation."""
