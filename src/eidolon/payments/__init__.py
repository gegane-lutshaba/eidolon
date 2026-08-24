"""AP2-aligned payment mandates.

Google's Agent Payments Protocol (AP2, Linux Foundation) makes agent-initiated
payments accountable with cryptographically-signed **mandates**: an *Intent
Mandate* (the principal authorizes a bounded intent — spend up to X with payee P
for purpose Z) and a *Cart Mandate* (the principal authorizes a specific cart).

EIDOLON already escalates every binding payment (`commit-action`) and, once the
principal approves it (the §7 approval workflow), holds a signed authorization for
exactly that action. This module turns that approval into an AP2-shaped, signed
:class:`PaymentMandate` a payment rail could honor — closing the loop from
"the twin wants to pay" to "the principal cryptographically authorized this
payment", attested end to end.
"""

from eidolon.payments.mandate import (
    CartMandate,
    IntentMandate,
    PaymentMandate,
    mandate_from_approval,
    verify_payment_mandate,
)

__all__ = [
    "PaymentMandate",
    "IntentMandate",
    "CartMandate",
    "mandate_from_approval",
    "verify_payment_mandate",
]
