"""AP2-aligned payment mandates (#11): an approved payment escalation becomes a
signed, verifiable mandate bounded by an Intent/Cart — and bound to the action.
"""

from __future__ import annotations

import pytest

from eidolon.common import crypto
from eidolon.escalation import make_approval
from eidolon.payments import (
    CartMandate,
    IntentMandate,
    mandate_from_approval,
    verify_payment_mandate,
)
from eidolon.payments.mandate import CartLine
from eidolon.sage.port import Scope
from eidolon.types import Action


def _payment_action():
    return Action(id="pay", action_class="commit-action", description="pay Acme invoice 12000",
                  scope=Scope(selectors={"project": ["ops"]}))


@pytest.fixture
def principal():
    return crypto.generate_keypair()


def test_mandate_from_approval_verifies(principal) -> None:
    pid = principal.public_key_hex
    approval = make_approval(_payment_action(), pid, principal.signing_key_hex)
    intent = IntentMandate(max_amount=20000, allowed_payees=["Acme"], purpose="accounts-payable")
    cart = CartMandate(lines=[CartLine(description="Dec invoice", amount=12000)])
    m = mandate_from_approval(approval=approval, principal_signing_key=principal.signing_key_hex,
                              payee="Acme", amount=12000, intent=intent, cart=cart)
    ok, reason = verify_payment_mandate(m)
    assert ok, reason
    assert m.action_digest == approval.action_digest  # bound to the escalated action
    assert m.not_after == approval.not_after


def test_tampered_amount_fails_verification(principal) -> None:
    pid = principal.public_key_hex
    approval = make_approval(_payment_action(), pid, principal.signing_key_hex)
    m = mandate_from_approval(approval=approval, principal_signing_key=principal.signing_key_hex,
                              payee="Acme", amount=100)
    tampered = m.model_copy(update={"amount": 99999})
    ok, reason = verify_payment_mandate(tampered)
    assert not ok and reason == "bad signature"


def test_cannot_issue_over_intent(principal) -> None:
    pid = principal.public_key_hex
    approval = make_approval(_payment_action(), pid, principal.signing_key_hex)
    intent = IntentMandate(max_amount=5000, allowed_payees=["Acme"])
    with pytest.raises(ValueError, match="exceeds intent"):
        mandate_from_approval(approval=approval, principal_signing_key=principal.signing_key_hex,
                              payee="Acme", amount=12000, intent=intent)


def test_cannot_issue_to_payee_outside_intent(principal) -> None:
    pid = principal.public_key_hex
    approval = make_approval(_payment_action(), pid, principal.signing_key_hex)
    intent = IntentMandate(max_amount=20000, allowed_payees=["Acme"])
    with pytest.raises(ValueError, match="payee not in intent"):
        mandate_from_approval(approval=approval, principal_signing_key=principal.signing_key_hex,
                              payee="Stranger", amount=100, intent=intent)


def test_cart_total_must_match_amount(principal) -> None:
    pid = principal.public_key_hex
    approval = make_approval(_payment_action(), pid, principal.signing_key_hex)
    cart = CartMandate(lines=[CartLine(description="x", amount=10), CartLine(description="y", amount=5)])
    with pytest.raises(ValueError, match="cart total"):
        mandate_from_approval(approval=approval, principal_signing_key=principal.signing_key_hex,
                              payee="Acme", amount=99, cart=cart)  # 99 != 15


def test_only_the_approving_principal_can_issue(principal) -> None:
    pid = principal.public_key_hex
    approval = make_approval(_payment_action(), pid, principal.signing_key_hex)
    imposter = crypto.generate_keypair()
    with pytest.raises(ValueError, match="approving principal"):
        mandate_from_approval(approval=approval, principal_signing_key=imposter.signing_key_hex,
                              payee="Acme", amount=1)
