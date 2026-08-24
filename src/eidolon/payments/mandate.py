"""AP2-aligned signed payment mandates.

A :class:`PaymentMandate` carries the AP2 accountability chain: who authorized
(the principal), what (payee, amount, currency), under what bounds (an
:class:`IntentMandate`) or for which specific cart (a :class:`CartMandate`), for
what purpose, until when — signed with the principal's Ed25519 key.
"""

from __future__ import annotations

import datetime as _dt

from pydantic import BaseModel, Field

from eidolon.common import crypto
from eidolon.common.canonical import canonical_bytes, content_hash


class IntentMandate(BaseModel):
    """AP2 Intent: the principal authorizes a bounded spending intent."""

    model_config = {"frozen": True}

    max_amount: float
    currency: str = "USD"
    allowed_payees: list[str] = Field(default_factory=list)  # empty = any within intent
    purpose: str | None = None


class CartLine(BaseModel):
    model_config = {"frozen": True}

    description: str
    amount: float


class CartMandate(BaseModel):
    """AP2 Cart: the principal authorizes one specific cart."""

    model_config = {"frozen": True}

    lines: list[CartLine]

    @property
    def total(self) -> float:
        return round(sum(x.amount for x in self.lines), 2)


class PaymentMandate(BaseModel):
    """A signed, accountable authorization for an agent-initiated payment."""

    model_config = {"frozen": True}

    payer_id: str  # the principal's Ed25519 pubkey (hex)
    payee: str
    amount: float
    currency: str = "USD"
    purpose: str | None = None
    intent: IntentMandate | None = None
    cart: CartMandate | None = None
    # Ties the payment to the action the twin escalated (the approval's digest).
    action_digest: str | None = None
    not_after: _dt.datetime
    signature: str = ""

    def _payload(self) -> bytes:
        body = self.model_dump(mode="json")
        body.pop("signature", None)
        return canonical_bytes(body)

    @property
    def id(self) -> str:
        return "pm-" + content_hash(self._payload())[:16]


def _sign(mandate: PaymentMandate, signing_key_hex: str) -> PaymentMandate:
    return mandate.model_copy(update={"signature": crypto.sign(signing_key_hex, mandate._payload())})


def verify_payment_mandate(mandate: PaymentMandate, now: _dt.datetime | None = None) -> tuple[bool, str]:
    """Verify signature, expiry, and that the payment respects its Intent/Cart bounds."""
    now = now or _dt.datetime.now(_dt.UTC)
    if now > mandate.not_after:
        return False, "expired"
    if not crypto.verify(mandate.payer_id, mandate._payload(), mandate.signature):
        return False, "bad signature"
    if mandate.intent is not None:
        if mandate.amount > mandate.intent.max_amount:
            return False, "amount exceeds intent"
        if mandate.intent.allowed_payees and mandate.payee not in mandate.intent.allowed_payees:
            return False, "payee not in intent"
        if mandate.intent.currency != mandate.currency:
            return False, "currency mismatch"
    if mandate.cart is not None and round(mandate.cart.total, 2) != round(mandate.amount, 2):
        return False, "amount != cart total"
    return True, "ok"


def mandate_from_approval(
    *,
    approval,  # eidolon.escalation.types.Approval
    principal_signing_key: str,
    payee: str,
    amount: float,
    currency: str = "USD",
    purpose: str | None = None,
    intent: IntentMandate | None = None,
    cart: CartMandate | None = None,
) -> PaymentMandate:
    """Issue a signed AP2 payment mandate from a principal's approval.

    The approver must be the principal; the mandate is bound to the approved
    action's digest and inherits its expiry (an approval already authorized *this*
    action — the mandate expresses it in AP2 terms a payment rail can verify).
    """
    payer_id = crypto.public_key_from_private(principal_signing_key)
    if payer_id != approval.approver_id:
        raise ValueError("payment mandate must be signed by the approving principal")
    mandate = PaymentMandate(
        payer_id=payer_id, payee=payee, amount=amount, currency=currency, purpose=purpose,
        intent=intent, cart=cart, action_digest=approval.action_digest, not_after=approval.not_after,
    )
    signed = _sign(mandate, principal_signing_key)
    ok, reason = verify_payment_mandate(signed)
    if not ok:
        raise ValueError(f"refusing to issue an invalid mandate: {reason}")
    return signed
