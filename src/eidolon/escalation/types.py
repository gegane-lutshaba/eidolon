"""Escalation + approval value types.

An :class:`Approval` is a signed, time-boxed authorization bound to one specific
action digest. It is the principal saying "yes, do exactly this" — verifiable
(Ed25519), single-purpose, and expiring.
"""

from __future__ import annotations

import datetime as _dt
from enum import Enum

from pydantic import BaseModel, Field

from eidolon.common import crypto
from eidolon.common.canonical import canonical_bytes, content_hash
from eidolon.types import Action


def action_digest(action: Action, principal_id: str) -> str:
    """Stable digest of the semantically-meaningful action fields + principal."""
    return content_hash(
        {
            "principal_id": principal_id,
            "action_class": action.action_class,
            "description": action.description,
            "scope": action.scope.selectors,
            "touches_exclusions": sorted(action.touches_exclusions),
            "budget_cost": action.budget_cost,
        }
    )


class Approval(BaseModel):
    """A signed, one-time, time-boxed approval for a specific action."""

    model_config = {"frozen": True}

    action_digest: str
    approver_id: str  # Ed25519 pubkey (hex) — must be the principal
    not_after: _dt.datetime
    signature: str

    def _payload(self) -> bytes:
        return canonical_bytes(
            {"action_digest": self.action_digest, "approver_id": self.approver_id,
             "not_after": self.not_after}
        )


def make_approval(action: Action, principal_id: str, signing_key_hex: str, *, ttl_seconds: int = 900) -> Approval:
    """Produce an approval for ``action``, signed by the principal."""
    approver_id = crypto.public_key_from_private(signing_key_hex)
    if approver_id != principal_id:
        raise ValueError("approval must be signed by the principal's key")
    not_after = _dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=ttl_seconds)
    digest = None  # filled below to keep signature over the final fields
    unsigned = Approval(
        action_digest=action_digest(action, principal_id),
        approver_id=approver_id, not_after=not_after, signature="",
    )
    digest = unsigned.action_digest  # noqa: F841 — clarity
    signature = crypto.sign(signing_key_hex, unsigned._payload())
    return unsigned.model_copy(update={"signature": signature})


def verify_approval(
    approval: Approval, action: Action, principal_id: str,
    now: _dt.datetime | None = None,
) -> bool:
    """True iff the approval is a valid, unexpired signature for this exact action."""
    now = now or _dt.datetime.now(_dt.UTC)
    if approval.approver_id != principal_id:
        return False
    if approval.action_digest != action_digest(action, principal_id):
        return False
    if now > approval.not_after:
        return False
    return crypto.verify(approval.approver_id, approval._payload(), approval.signature)


class EscalationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class EscalationRequest(BaseModel):
    """A decision the twin handed back, awaiting the principal."""

    id: str
    principal_id: str
    action: Action
    action_class: str
    rationale: str
    message: str | None = None  # the twin's escalation text / draft
    created_at: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.UTC))
    expires_at: _dt.datetime | None = None
    status: EscalationStatus = EscalationStatus.PENDING
    approval: Approval | None = None
