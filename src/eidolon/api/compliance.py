"""Compliance & audit packs.

Assemble, for a team over a date range, a hash-sealed evidence bundle from the
governed-action record: a summary (actions governed / denied / escalated /
killed, per agent), the underlying attestations, the ledger's tamper-evidence
status, and a control-mapping appendix (SOC2 / EU AI Act). Downloadable as a
self-describing JSON pack whose ``bundle_hash`` lets a recipient detect any
post-export tampering of the file itself.

Honest by construction: every number is counted from the real
``gateway_events`` for the team's agents; the mapping states which EIDOLON
control satisfies each framework clause and points at the evidence.
"""

from __future__ import annotations

import datetime as _dt

from eidolon.common.canonical import content_hash

DEFAULT_RETENTION_DAYS = 90

# How EIDOLON's mechanisms map onto common framework clauses. Evidence is the
# concrete artifact in this bundle / platform that demonstrates the control.
CONTROLS = [
    {"control": "Default-deny authorization",
     "mechanism": "THEMIS Ed25519 delegation credentials checked on every tool call",
     "soc2": "CC6.1 logical access", "eu_ai_act": "Art.14 human oversight",
     "evidence": "denied/escalated counts + per-action attestations"},
    {"control": "Attest-then-act (no unattested side effect)",
     "mechanism": "KAIROS writes a HORKOS attestation before any action runs",
     "soc2": "CC7.2 monitoring", "eu_ai_act": "Art.12 record-keeping / logging",
     "evidence": "attestation_hash on every event"},
    {"control": "Tamper-evident audit trail",
     "mechanism": "append-only hash-chained ledger (verify_chain)",
     "soc2": "CC7.1 integrity", "eu_ai_act": "Art.12 automatic logging",
     "evidence": "ledger chain status in this bundle"},
    {"control": "Immediate revocation / kill switch",
     "mechanism": "operator kill flag denies the agent's next action",
     "soc2": "CC6.1 access revocation", "eu_ai_act": "Art.14 stop button",
     "evidence": "KILLED events"},
    {"control": "Data-flow exfiltration control",
     "mechanism": "CaMeL-style taint from sensitive reads to egress calls",
     "soc2": "CC6.7 data transmission", "eu_ai_act": "Art.10 data governance",
     "evidence": "DENY events on egress carrying tainted values"},
    {"control": "Human-in-the-loop approval",
     "mechanism": "escalations require a signed, one-time approval",
     "soc2": "CC6.1", "eu_ai_act": "Art.14 human oversight",
     "evidence": "ESCALATE events + approval inbox"},
    {"control": "Adversarial robustness testing",
     "mechanism": "certification against the attack library (VERSUS/BASANOS)",
     "soc2": "CC7.1", "eu_ai_act": "Art.9 risk mgmt / Art.15 robustness",
     "evidence": "agent certificates"},
]


def _as_utc(dt: _dt.datetime | None) -> _dt.datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_dt.UTC)


def _is_exfil(level: str, rationale: str | None) -> bool:
    if level != "DENY" or not rationale:
        return False
    r = rationale.lower()
    return "exfil" in r or "data-exfiltration" in r


def governance_summary(sf, *, agent_ids: set[str], since: _dt.datetime,
                       until: _dt.datetime, max_rows: int = 20000) -> dict:
    """A readable governance posture for one org + window: the attested ledger
    turned into the answer IT asks — are agents acting in scope, what's held for
    approval, what's denied, and how many data-exfiltration attempts were blocked
    — broken down per agent and per action class. Counts only (no attestations),
    so it's cheap enough for a dashboard.
    """
    from sqlalchemy import select

    from eidolon.data.models import GatewayEventRow

    out: dict = {
        "actions_governed": 0, "allowed": 0, "held": 0, "denied": 0, "killed": 0,
        "exfil_blocked": 0, "by_action_class": {}, "by_agent": {}, "top_blocked": [],
        "agents_active": 0, "truncated": False,
        "period": {"from": since.isoformat(), "to": until.isoformat()},
    }
    if not agent_ids:
        return out
    with sf() as s:
        rows = s.execute(
            select(GatewayEventRow.gateway_id, GatewayEventRow.agent,
                   GatewayEventRow.action_class, GatewayEventRow.level,
                   GatewayEventRow.allowed, GatewayEventRow.rationale)
            .where(GatewayEventRow.gateway_id.in_(agent_ids),
                   GatewayEventRow.ts >= since, GatewayEventRow.ts <= until)
            .order_by(GatewayEventRow.seq.desc()).limit(max_rows + 1)
        ).all()
    out["truncated"] = len(rows) > max_rows
    for gid, agent, cls, level, allowed, rationale in rows[:max_rows]:
        lvl = (level or "").upper()
        out["actions_governed"] += 1
        acls = out["by_action_class"].setdefault(cls or "unmapped", {"total": 0, "blocked": 0})
        acls["total"] += 1
        ag = out["by_agent"].setdefault(gid, {"agent": agent, "total": 0, "allowed": 0,
                                              "held": 0, "denied": 0, "exfil_blocked": 0})
        ag["total"] += 1
        if lvl in ("DENY", "KILLED"):
            out["denied" if lvl == "DENY" else "killed"] += 1
            ag["denied"] += 1
            acls["blocked"] += 1
            if _is_exfil(lvl, rationale):
                out["exfil_blocked"] += 1
                ag["exfil_blocked"] += 1
        elif allowed:
            out["allowed"] += 1
            ag["allowed"] += 1
        else:  # ESCALATE / DRAFT — held for a human
            out["held"] += 1
            ag["held"] += 1
    out["agents_active"] = len(out["by_agent"])
    out["top_blocked"] = sorted(
        ({"gateway_id": gid, **v} for gid, v in out["by_agent"].items()),
        key=lambda a: (a["denied"], a["exfil_blocked"]), reverse=True)[:5]
    return out


def build_report(sf, *, org: dict, agent_ids: set[str], since: _dt.datetime,
                 until: _dt.datetime, chain: dict, generated_at: _dt.datetime,
                 max_rows: int = 5000) -> dict:
    """A hash-sealed compliance evidence bundle for one org + window."""
    from sqlalchemy import select

    from eidolon.data.models import GatewayEventRow

    events: list[dict] = []
    by_level: dict[str, int] = {}
    by_agent: dict[str, dict] = {}
    if agent_ids:
        with sf() as s:
            rows = s.execute(
                select(GatewayEventRow)
                .where(GatewayEventRow.gateway_id.in_(agent_ids),
                       GatewayEventRow.ts >= since, GatewayEventRow.ts <= until)
                .order_by(GatewayEventRow.ts.asc()).limit(max_rows)
            ).scalars().all()
        for r in rows:
            by_level[r.level] = by_level.get(r.level, 0) + 1
            a = by_agent.setdefault(r.gateway_id, {"agent": r.agent, "total": 0, "blocked": 0})
            a["total"] += 1
            if r.level in ("DENY", "KILLED"):
                a["blocked"] += 1
            events.append({
                "ts": r.ts.isoformat() if r.ts else None, "gateway_id": r.gateway_id,
                "agent": r.agent, "tool": r.tool, "action_class": r.action_class,
                "level": r.level, "allowed": r.allowed,
                "attestation_hash": r.attestation_hash,
            })

    total = len(events)
    blocked = by_level.get("DENY", 0) + by_level.get("KILLED", 0)
    body = {
        "kind": "eidolon.compliance-pack.v1",
        "org": {"id": org["id"], "name": org["name"]},
        "period": {"from": since.isoformat(), "to": until.isoformat()},
        "retention_days": org.get("retention_days") or DEFAULT_RETENTION_DAYS,
        "generated_at": generated_at.isoformat(),
        "summary": {
            "actions_governed": total,
            "by_outcome": by_level,
            "blocked": blocked,
            "agents": [{"gateway_id": gid, **v} for gid, v in by_agent.items()],
        },
        "ledger_integrity": chain,
        "controls": CONTROLS,
        "attestations": events,
        "note": "Counts are from this platform's governed-action record for the "
                "team's agents. ledger_integrity attests the tamper-evident hash "
                "chain; a broken chain is reported with the first affected entry.",
    }
    body["bundle_hash"] = content_hash(body)
    return body
