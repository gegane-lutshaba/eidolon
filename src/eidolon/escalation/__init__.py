"""Escalation approval workflow.

KAIROS hands a decision back to the principal with ESCALATE. This turns that
return value into a real product surface: escalations become pending items in an
approval inbox; the principal (or an authorized approver) approves one by
*signing* it, producing a one-time, time-boxed :class:`Approval`; and KAIROS then
executes exactly that action under the approval — attested — via
``resolve_with_approval``.

An approval can only *release an escalation the twin already surfaced*: it never
grants authority the credential lacks (out-of-scope, revoked, unpermitted class
still DENY), and it is bound to one specific action digest.
"""

from eidolon.escalation.queue import EscalationQueue
from eidolon.escalation.types import (
    Approval,
    EscalationRequest,
    action_digest,
    make_approval,
    verify_approval,
)

__all__ = [
    "EscalationQueue",
    "EscalationRequest",
    "Approval",
    "action_digest",
    "make_approval",
    "verify_approval",
]
