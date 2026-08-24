# Payments — AP2 mandates

Every binding payment is a `commit-action`, which **always escalates**. Once the
principal approves it (the [escalation workflow](review-and-related-work.md), §7),
EIDOLON holds a signed authorization for exactly that action. `eidolon.payments`
turns that approval into a mandate shaped like Google's **Agent Payments Protocol
(AP2)** — the cryptographic accountability a payment rail needs to honor an
agent-initiated payment.

```python
from eidolon.escalation import make_approval
from eidolon.payments import IntentMandate, CartMandate, mandate_from_approval, verify_payment_mandate
from eidolon.payments.mandate import CartLine

approval = make_approval(payment_action, principal_id, principal_key)   # from the §7 approval loop
mandate = mandate_from_approval(
    approval=approval, principal_signing_key=principal_key,
    payee="Acme", amount=12000, purpose="accounts-payable",
    intent=IntentMandate(max_amount=20000, allowed_payees=["Acme"]),    # AP2 Intent Mandate
    cart=CartMandate(lines=[CartLine(description="Dec invoice", amount=12000)]),  # AP2 Cart Mandate
)
verify_payment_mandate(mandate)   # (True, "ok")
```

## Mapping to AP2

| AP2 concept | EIDOLON |
|---|---|
| **Intent Mandate** (bounded spending intent) | `IntentMandate(max_amount, allowed_payees, currency, purpose)` |
| **Cart Mandate** (specific cart) | `CartMandate(lines)` — total must equal the payment amount |
| Cryptographic accountability | `PaymentMandate` signed with the principal's Ed25519 key |
| Human authorization | the §7 `Approval` — the mandate is bound to its **action digest** and inherits its expiry |
| Verifiable by the rail | `verify_payment_mandate` checks signature, expiry, and Intent/Cart bounds |

## Safety properties (tested)

- A mandate is **only issued by the approving principal** (not the twin, not a
  third party).
- It is **bound to the exact action** the twin escalated (the approval's digest),
  so it can't be reused for a different payment.
- It **respects its bounds**: over-intent amount, out-of-intent payee, and a cart
  total that doesn't equal the amount are all rejected *at issuance* — an invalid
  mandate is never produced.
- Tampering breaks the signature.

This closes the loop from *"the twin wants to pay"* → *"the principal
cryptographically authorized this payment, within these bounds, for this
purpose"* — attested end to end, and expressible in the emerging agent-payments
standard. (A live rail integration is out of scope; this is the mandate layer.)
