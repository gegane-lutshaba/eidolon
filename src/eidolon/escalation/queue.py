"""The approval inbox.

Records escalations, lets the principal approve (by signing) or deny them, and
expires stale ones. Two implementations of one contract: the in-memory queue
for the fast lane, and :class:`PostgresEscalationQueue` for deployments — a
restart must not lose pending approvals or the execution context needed to
re-execute an approved action.
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
        self._contexts: dict[str, dict] = {}  # request_id -> {"chain": [...], "certificates": [...]}
        self._ttl = default_ttl_seconds
        self._ids = itertools.count(1)

    def enqueue(
        self,
        decision: Decision,
        action: Action,
        context: Context,
        exec_context: dict | None = None,
    ) -> EscalationRequest:
        """Record an escalated (or drafted) decision as a pending approval item.

        ``exec_context`` (delegation chain + certificates, JSON-serializable)
        is kept with the item so an approval can re-execute the exact action.
        """
        if decision.level not in (DecisionLevel.ESCALATE, DecisionLevel.DRAFT):
            raise ValueError("only ESCALATE/DRAFT decisions are enqueued for approval")
        rid = f"esc-{next(self._ids)}"
        req = EscalationRequest(
            id=rid, principal_id=context.principal_id, action=action,
            action_class=action.action_class, rationale=decision.rationale,
            message=decision.output,
            expires_at=_dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=self._ttl),
        )
        self._put(req, exec_context or {})
        return req

    def list_pending(self, principal_id: str) -> list[EscalationRequest]:
        self.expire_stale()
        return [r for r in self._all()
                if r.principal_id == principal_id and r.status == EscalationStatus.PENDING]

    def list_all_pending(self) -> list[EscalationRequest]:
        """Every pending item across principals — the operator approval inbox."""
        self.expire_stale()
        return [r for r in self._all() if r.status == EscalationStatus.PENDING]

    def get(self, request_id: str) -> EscalationRequest | None:
        return self._items.get(request_id)

    def exec_context_for(self, request_id: str) -> dict:
        """The stored delegation chain + certificates for re-execution."""
        return self._contexts.get(request_id, {})

    def approve(self, request_id: str, principal_signing_key: str) -> Approval:
        """Principal approves by signing the exact action. Returns the Approval."""
        req = self._require_pending(request_id)
        approval = make_approval(req.action, req.principal_id, principal_signing_key,
                                 ttl_seconds=self._ttl)
        self._put(req.model_copy(
            update={"status": EscalationStatus.APPROVED, "approval": approval}))
        return approval

    def deny(self, request_id: str) -> None:
        req = self._require_pending(request_id)
        self._put(req.model_copy(update={"status": EscalationStatus.DENIED}))

    def expire_stale(self, now: _dt.datetime | None = None) -> None:
        now = now or _dt.datetime.now(_dt.UTC)
        for req in self._all():
            if req.status == EscalationStatus.PENDING and req.expires_at and now > req.expires_at:
                self._put(req.model_copy(update={"status": EscalationStatus.EXPIRED}))

    # -- storage hooks (overridden by the Postgres queue) ------------------
    def _put(self, req: EscalationRequest, exec_context: dict | None = None) -> None:
        self._items[req.id] = req
        if exec_context is not None:
            self._contexts[req.id] = exec_context

    def _all(self) -> list[EscalationRequest]:
        return list(self._items.values())

    def _require_pending(self, request_id: str) -> EscalationRequest:
        req = self.get(request_id)
        if req is None:
            raise KeyError(f"no escalation {request_id!r}")
        self.expire_stale()
        req = self.get(request_id)
        if req.status != EscalationStatus.PENDING:
            raise ValueError(f"escalation {request_id!r} is {req.status.value}, not pending")
        return req


class PostgresEscalationQueue(EscalationQueue):
    """Durable approval inbox over the operational store.

    Same contract as the in-memory queue; pending items and their execution
    context survive a service restart. Ids are derived from the row count, and
    lookups always hit the database (no process-local cache to go stale).
    """

    def __init__(self, *, default_ttl_seconds: int = 900, session_factory=None) -> None:
        super().__init__(default_ttl_seconds=default_ttl_seconds)
        if session_factory is None:
            from eidolon.data.db import get_sessionmaker, init_db

            init_db()
            session_factory = get_sessionmaker()
        self._sf = session_factory
        # Continue id numbering after any existing rows.
        from eidolon.data.models import EscalationRow

        with self._sf() as s:
            count = s.query(EscalationRow).count()
        self._ids = itertools.count(count + 1)

    def _put(self, req: EscalationRequest, exec_context: dict | None = None) -> None:
        from eidolon.data.models import EscalationRow

        with self._sf() as s:
            row = s.get(EscalationRow, req.id)
            if row is None:
                row = EscalationRow(id=req.id, principal_id=req.principal_id,
                                    exec_context=exec_context or {})
                s.add(row)
            row.status = req.status.value
            row.payload = req.model_dump(mode="json")
            if exec_context is not None:
                row.exec_context = exec_context
            s.commit()

    def _all(self) -> list[EscalationRequest]:
        from eidolon.data.models import EscalationRow

        with self._sf() as s:
            rows = s.query(EscalationRow).order_by(EscalationRow.created_at.asc()).all()
        return [EscalationRequest.model_validate(r.payload) for r in rows]

    def get(self, request_id: str) -> EscalationRequest | None:
        from eidolon.data.models import EscalationRow

        with self._sf() as s:
            row = s.get(EscalationRow, request_id)
        return EscalationRequest.model_validate(row.payload) if row else None

    def exec_context_for(self, request_id: str) -> dict:
        from eidolon.data.models import EscalationRow

        with self._sf() as s:
            row = s.get(EscalationRow, request_id)
        return row.exec_context or {} if row else {}
