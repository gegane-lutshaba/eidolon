"""KAIROS value types (PRD §6.4)."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from enum import Enum

from pydantic import BaseModel

from eidolon.profile.schema import AutonomyLevel


class DecisionLevel(str, Enum):
    DENY = "DENY"
    ESCALATE = "ESCALATE"
    DRAFT = "DRAFT"
    NOTIFY_ACT = "NOTIFY_ACT"
    AUTONOMOUS_ACT = "AUTONOMOUS_ACT"


# Map an effective autonomy level onto the actionable gate outcome. ``observe``
# means the twin is not cleared to act on this class, so it hands the decision
# back (ESCALATE) rather than executing.
_AUTONOMY_TO_LEVEL: dict[AutonomyLevel, DecisionLevel] = {
    "observe": DecisionLevel.ESCALATE,
    "draft": DecisionLevel.DRAFT,
    "notify": DecisionLevel.NOTIFY_ACT,
    "autonomous": DecisionLevel.AUTONOMOUS_ACT,
}


def level_for_autonomy(level: AutonomyLevel) -> DecisionLevel:
    return _AUTONOMY_TO_LEVEL[level]


class Decision(BaseModel):
    level: DecisionLevel
    rationale: str
    attestation_hash: str | None = None
    # Populated when the gate produced output the caller can use.
    output: str | None = None  # draft text or escalation message
    action_class: str | None = None


class BudgetLedger:
    """Blast-radius consumption per principal per dimension.

    Dimensions named ``*_per_window`` (``posts_per_window``,
    ``egress_per_window``…) count only within a rolling window of
    ``window_seconds``; every other dimension is a lifetime counter (e.g.
    ``scope_expansion``, always 0). ``would_exceed`` is checked in KAIROS step 1;
    ``consume`` runs only after a successful attest-then-act.

    In-process by default; :class:`SqliteBudgetLedger` and
    :class:`PostgresBudgetLedger` persist the same events so a restart doesn't
    reset the budget and several processes share it.
    """

    def __init__(self, window_seconds: int = 3600,
                 clock: Callable[[], _dt.datetime] | None = None) -> None:
        self._window = _dt.timedelta(seconds=window_seconds)
        self._clock = clock or (lambda: _dt.datetime.now(_dt.UTC))
        self._events: dict[tuple[str, str], list[tuple[_dt.datetime, int]]] = {}

    @staticmethod
    def windowed(dim: str) -> bool:
        return dim.endswith("_per_window")

    def _since(self, dim: str) -> _dt.datetime | None:
        return self._clock() - self._window if self.windowed(dim) else None

    # storage hooks (overridden by the durable ledgers) -----------------------
    def _sum(self, principal_id: str, dim: str, since: _dt.datetime | None) -> int:
        events = self._events.get((principal_id, dim), [])
        if since is not None:  # prune what fell out of the window
            events = [e for e in events if e[0] > since]
            self._events[(principal_id, dim)] = events
        return sum(a for _, a in events)

    def _record(self, principal_id: str, dim: str, amount: int, at: _dt.datetime) -> None:
        self._events.setdefault((principal_id, dim), []).append((at, amount))

    # contract ---------------------------------------------------------------
    def consumed(self, principal_id: str, dim: str) -> int:
        return self._sum(principal_id, dim, self._since(dim))

    def would_exceed(self, principal_id: str, cost: dict[str, int], limits: dict[str, int]) -> str | None:
        for dim, amount in cost.items():
            limit = limits.get(dim)
            if limit is None:
                continue
            if self.consumed(principal_id, dim) + amount > limit:
                return dim
        return None

    def consume(self, principal_id: str, cost: dict[str, int]) -> None:
        now = self._clock()
        for dim, amount in cost.items():
            if amount:
                self._record(principal_id, dim, amount, now)


class SqliteBudgetLedger(BudgetLedger):
    """Budget events in the local state file (shared with the revocation store)."""

    def __init__(self, path_or_db, window_seconds: int = 3600,
                 clock: Callable[[], _dt.datetime] | None = None) -> None:
        super().__init__(window_seconds, clock)
        from eidolon.common.state_db import StateDB

        self._db = path_or_db if isinstance(path_or_db, StateDB) else StateDB(path_or_db)

    def _sum(self, principal_id: str, dim: str, since: _dt.datetime | None) -> int:
        if since is None:
            rows = self._db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_events WHERE principal_id=? AND dim=?",
                (principal_id, dim))
        else:
            rows = self._db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_events "
                "WHERE principal_id=? AND dim=? AND ts > ?", (principal_id, dim, since.isoformat()))
        return int(rows[0][0])

    def _record(self, principal_id: str, dim: str, amount: int, at: _dt.datetime) -> None:
        self._db.execute("INSERT INTO budget_events VALUES (?, ?, ?, ?)",
                         (principal_id, dim, at.isoformat(), amount))


class PostgresBudgetLedger(BudgetLedger):
    """Budget events in the operational store (the postgres backend)."""

    def __init__(self, window_seconds: int = 3600,
                 clock: Callable[[], _dt.datetime] | None = None, session_factory=None) -> None:
        super().__init__(window_seconds, clock)
        if session_factory is None:
            from eidolon.data.db import get_sessionmaker, init_db

            init_db()
            session_factory = get_sessionmaker()
        self._sf = session_factory

    def _sum(self, principal_id: str, dim: str, since: _dt.datetime | None) -> int:
        from sqlalchemy import func, select

        from eidolon.data.models import BudgetEventRow

        q = select(func.coalesce(func.sum(BudgetEventRow.amount), 0)).where(
            BudgetEventRow.principal_id == principal_id, BudgetEventRow.dim == dim)
        if since is not None:
            q = q.where(BudgetEventRow.ts > since)
        with self._sf() as s:
            return int(s.execute(q).scalar() or 0)

    def _record(self, principal_id: str, dim: str, amount: int, at: _dt.datetime) -> None:
        from eidolon.data.models import BudgetEventRow

        with self._sf() as s:
            s.add(BudgetEventRow(principal_id=principal_id, dim=dim, ts=at, amount=amount))
            s.commit()
