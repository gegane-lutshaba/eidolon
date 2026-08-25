"""The approval inbox.

Records escalations, lets the principal approve (by signing) or deny them, and
expires stale ones. In-memory here; a deployment would persist to the operational
store and notify the principal over their channel of choice.
"""

from __future__ import annotations

import datetime as _dt
import itertools

from eidolon.escalation.types import (
    Approval,
    EscalationRequest,
    EscalationStatus,
    make_approval,
)
from eidolon.kairos.types import Decision, DecisionLevel
from eidolon.types import Action, Context


class EscalationQueue:
    def __init__(self, *, default_ttl_seconds: int = 900) -> None:
        self._items: dict[str, EscalationRequest] = {}
        self._ttl = default_ttl_seconds
        self._ids = itertools.count(1)

    def enqueue(self, decision: Decision, action: Action, context: Context) -> EscalationRequest:
        """Record an escalated (or drafted) decision as a pending approval item."""
        if decision.level not in (DecisionLevel.ESCALATE, DecisionLevel.DRAFT):
            raise ValueError("only ESCALATE/DRAFT decisions are enqueued for approval")
        rid = f"esc-{next(self._ids)}"
        req = EscalationRequest(
            id=rid, principal_id=context.principal_id, action=action,
            action_class=action.action_class, rationale=decision.rationale,
            message=decision.output,
            expires_at=_dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=self._ttl),
        )
        self._items[rid] = req
        return req

    def list_pending(self, principal_id: str) -> list[EscalationRequest]:
        self.expire_stale()
        return [r for r in self._items.values()
                if r.principal_id == principal_id and r.status == EscalationStatus.PENDING]

    def list_all_pending(self) -> list[EscalationRequest]:
        """Every pending item across principals — the operator approval inbox."""
        self.expire_stale()
        return [r for r in self._items.values() if r.status == EscalationStatus.PENDING]

    def get(self, request_id: str) -> EscalationRequest | None:
        return self._items.get(request_id)

    def approve(self, request_id: str, principal_signing_key: str) -> Approval:
        """Principal approves by signing the exact action. Returns the Approval."""
        req = self._require_pending(request_id)
        approval = make_approval(req.action, req.principal_id, principal_signing_key,
                                 ttl_seconds=self._ttl)
        self._items[request_id] = req.model_copy(
            update={"status": EscalationStatus.APPROVED, "approval": approval})
        return approval

    def deny(self, request_id: str) -> None:
        req = self._require_pending(request_id)
        self._items[request_id] = req.model_copy(update={"status": EscalationStatus.DENIED})

    def expire_stale(self, now: _dt.datetime | None = None) -> None:
        now = now or _dt.datetime.now(_dt.UTC)
        for rid, req in list(self._items.items()):
            if req.status == EscalationStatus.PENDING and req.expires_at and now > req.expires_at:
                self._items[rid] = req.model_copy(update={"status": EscalationStatus.EXPIRED})

    def _require_pending(self, request_id: str) -> EscalationRequest:
        req = self._items.get(request_id)
        if req is None:
            raise KeyError(f"no escalation {request_id!r}")
        self.expire_stale()
        req = self._items[request_id]
        if req.status != EscalationStatus.PENDING:
            raise ValueError(f"escalation {request_id!r} is {req.status.value}, not pending")
        return req
