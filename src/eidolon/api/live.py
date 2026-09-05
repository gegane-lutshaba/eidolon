"""Mission control: gateway event ingest + live fan-out (SSE).

Gateways anywhere (a laptop, a server) report each governed decision here over
HTTPS with a gateway key. The platform stores the event (the mission-control
feed + replay), fans it out to live SSE subscribers, and answers with the
gateway's **kill state** — the console's red button takes effect on the
gateway's next report.

Reporting is telemetry: the gate itself runs inside the gateway, local and
fail-closed. Losing the platform never loosens an agent's authority — it only
dims the dashboard.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import threading
from collections import deque
from typing import Any

from pydantic import BaseModel, Field

# Feed retention: keep the table bounded (delete oldest past this many rows).
MAX_EVENT_ROWS = 20_000
REPLAY_ON_CONNECT = 50


class GatewayEvent(BaseModel):
    """One governed decision, as reported by a gateway."""

    gateway_id: str
    agent: str = ""
    tool: str
    action_class: str = ""
    level: str
    allowed: bool = False
    attestation_hash: str | None = None
    summary: str = ""  # redacted argument summary (never raw arguments)
    rationale: str = ""
    ts: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.UTC))


class LiveHub:
    """In-process pub/sub bridging sync publishers to async SSE subscribers.

    Sync endpoints run in worker threads; SSE generators run on the event
    loop. ``publish`` is thread-safe via ``call_soon_threadsafe``.
    """

    def __init__(self, replay: int = REPLAY_ON_CONNECT) -> None:
        self._subscribers: dict[int, tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = {}
        self._recent: deque[dict] = deque(maxlen=replay)
        self._lock = threading.Lock()
        self._next_id = 0

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._recent.append(event)
            targets = list(self._subscribers.values())
        for queue, loop in targets:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                pass  # subscriber's loop is gone; unsubscribe cleans it up

    def subscribe(self) -> tuple[int, asyncio.Queue, list[dict]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        loop = asyncio.get_running_loop()
        with self._lock:
            sid = self._next_id
            self._next_id += 1
            self._subscribers[sid] = (queue, loop)
            backlog = list(self._recent)
        return sid, queue, backlog

    def unsubscribe(self, sid: int) -> None:
        with self._lock:
            self._subscribers.pop(sid, None)


def sse_format(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


# -- storage/service (operational store) ----------------------------------
def record_event(session_factory, event: GatewayEvent) -> bool:
    """Persist one event + update the gateway card. Returns the KILL state."""
    from sqlalchemy import select

    from eidolon.data.models import GatewayEventRow, GatewayRow

    with session_factory() as s:
        gw = s.get(GatewayRow, event.gateway_id)
        if gw is None:
            gw = GatewayRow(id=event.gateway_id, agent=event.agent)
            s.add(gw)
        gw.agent = event.agent or gw.agent
        gw.last_seen = event.ts
        gw.events = (gw.events or 0) + 1
        s.add(GatewayEventRow(
            gateway_id=event.gateway_id, agent=event.agent, tool=event.tool,
            action_class=event.action_class, level=event.level, allowed=event.allowed,
            attestation_hash=event.attestation_hash, summary=event.summary[:500],
            rationale=event.rationale[:500], ts=event.ts,
        ))
        killed = bool(gw.killed)
        # Bounded feed: drop the oldest rows beyond the cap (cheap check).
        if gw.events % 200 == 0:
            oldest_keep = s.execute(
                select(GatewayEventRow.seq).order_by(GatewayEventRow.seq.desc())
                .offset(MAX_EVENT_ROWS).limit(1)
            ).scalar()
            if oldest_keep is not None:
                s.query(GatewayEventRow).filter(GatewayEventRow.seq <= oldest_keep).delete()
        s.commit()
    return killed


def set_killed(session_factory, gateway_id: str, killed: bool) -> bool:
    """Flip a gateway's kill switch. Returns False if the gateway is unknown."""
    from eidolon.data.models import GatewayRow

    with session_factory() as s:
        gw = s.get(GatewayRow, gateway_id)
        if gw is None:
            return False
        gw.killed = killed
        s.commit()
    return True


def list_gateways(session_factory) -> list[dict]:
    from sqlalchemy import select

    from eidolon.data.models import GatewayRow

    with session_factory() as s:
        rows = s.execute(select(GatewayRow).order_by(GatewayRow.last_seen.desc())).scalars().all()
        return [
            {"id": g.id, "agent": g.agent, "killed": g.killed,
             "last_seen": g.last_seen.isoformat() if g.last_seen else None,
             "events": g.events}
            for g in rows
        ]


def recent_events(session_factory, limit: int = REPLAY_ON_CONNECT) -> list[dict]:
    from sqlalchemy import select

    from eidolon.data.models import GatewayEventRow

    with session_factory() as s:
        rows = s.execute(
            select(GatewayEventRow).order_by(GatewayEventRow.seq.desc()).limit(limit)
        ).scalars().all()
    return [
        {"gateway_id": r.gateway_id, "agent": r.agent, "tool": r.tool,
         "action_class": r.action_class, "level": r.level, "allowed": r.allowed,
         "attestation_hash": r.attestation_hash, "summary": r.summary,
         "rationale": r.rationale, "ts": r.ts.isoformat() if r.ts else None}
        for r in reversed(rows)
    ]
