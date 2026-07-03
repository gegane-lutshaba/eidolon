#!/usr/bin/env python
"""EIDOLON governing MCP gateway — self-contained demo (no external framework).

Shows EIDOLON as the *authority layer* for MCP agents: an on-call ops agent's
tools are routed through the gateway, so every tool call is governed by KAIROS —
read tools run, drafts are held, status posts notify, and dangerous tools
(email a customer, delete prod) are refused. A short coda governs a red-teamer's
security tools with the offensive-security profile.

The gateway here calls the governance engine directly against a mock downstream
tool server, so it runs anywhere with `uv run`. The *real* MCP proxy (same
engine) is `python -m eidolon.gateway`; see docs/integrations/ for wiring it into
Hermes or Claude Code.
"""

from __future__ import annotations

import os
import sys

from eidolon.common import crypto
from eidolon.gateway.config import GatewayConfig, build_engine
from eidolon.gateway.mapping import ToolPolicy
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import ReplayFilter, Scope

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code, t):  return f"\033[{code}m{t}\033[0m" if _COLOR else t
def bold(t):  return _c("1", t)
def dim(t):   return _c("2", t)
def green(t): return _c("32", t)
def amber(t): return _c("33", t)
def red(t):   return _c("31", t)
def cyan(t):  return _c("36", t)

_STYLE = {"AUTONOMOUS_ACT": (green, "✅"), "NOTIFY_ACT": (green, "📢"),
          "DRAFT": (cyan, "✍️ "), "ESCALATE": (amber, "🛑"), "DENY": (red, "⛔")}


def title(t):
    print("\n" + dim("━" * 74))
    print(bold("  " + t))
    print(dim("━" * 74))


def run_call(engine, downstream, tool, args, *, naive=None):
    r = engine.govern(tool, args, downstream)
    style, icon = _STYLE.get(r.level, (dim, "•"))
    ran = green("REAL TOOL RAN") if r.allowed else red("tool NOT called")
    print(f"\n  {bold(tool)}({dim(', '.join(f'{k}={v}' for k,v in args.items()))})")
    print(f"    class={dim(r.action_class)} → {style(icon + ' ' + r.level)}   {ran}")
    if r.result is not None:
        print(f"    {dim('result:')} {r.result}")
    if r.message:
        print(f"    {cyan(r.message)}")
    print(f"    {dim('attested:')} {dim((r.attestation_hash or '')[:16])}")
    if naive:
        print(f"    {red('a naive MCP agent would:')} {naive}")
    return r


def ops_story():
    title("EIDOLON gateway — an on-call ops agent's MCP tools, governed")
    print(dim("  The agent is unchanged; it just calls tools. EIDOLON governs each call."))

    key = crypto.generate_keypair()
    principal = key.public_key_hex
    # Grounding for ETHOS fidelity (in production this comes from capture).
    seeds = []
    for phrase in [
        "the on-call engineer will get deploy status for each service routinely",
        "the on-call engineer will read the runbook for incidents routinely",
        "the on-call engineer will draft incident email updates for the team",
        "the on-call engineer will post status page updates during incidents",
    ]:
        seeds += [phrase] * 6

    cfg = GatewayConfig(
        profile_id="general-continuity",
        principal_signing_key=key.signing_key_hex,
        scope={"project": ["ops"]},
        seed_memories=seeds,
        tool_policies=[
            ToolPolicy(tool="get_deploy_status", action_class="answer-status",
                       scope=Scope(selectors={"project": ["ops"]})),
            ToolPolicy(tool="read_runbook", action_class="retrieve-context",
                       scope=Scope(selectors={"project": ["ops"]})),
            ToolPolicy(tool="draft_incident_email", action_class="draft-comm",
                       scope=Scope(selectors={"project": ["ops"]})),
            ToolPolicy(tool="post_status_page", action_class="post-status",
                       scope=Scope(selectors={"project": ["ops"]}), budget_cost={"posts_per_window": 1}),
            ToolPolicy(tool="send_customer_email", action_class="draft-comm",
                       touches_exclusions=["external-client-comm"],
                       scope=Scope(selectors={"project": ["ops"]})),
            ToolPolicy(tool="delete_database", action_class="commit-action",
                       touches_exclusions=["destructive-action"],
                       scope=Scope(selectors={"project": ["ops"]})),
        ],
    )
    sage = InMemorySagePort()
    engine = build_engine(cfg, sage=sage)

    # A mock downstream MCP tool server. Dangerous tools raise if ever called —
    # proving the gateway never forwards them.
    def downstream(tool, args):
        return {
            "get_deploy_status": lambda: f"{args.get('service','?')}: healthy, last deploy 2h ago",
            "read_runbook": lambda: f"runbook '{args.get('name','?')}': 1) page on-call 2) check dashboards",
            "post_status_page": lambda: f"posted to status page: {args.get('message','')!r}",
            "send_customer_email": lambda: (_ for _ in ()).throw(AssertionError("must never run")),
            "delete_database": lambda: (_ for _ in ()).throw(AssertionError("must never run")),
        }[tool]()

    run_call(engine, downstream, "get_deploy_status", {"service": "atlas"})
    run_call(engine, downstream, "read_runbook", {"name": "incident"})
    run_call(engine, downstream, "draft_incident_email", {"to": "team"})
    run_call(engine, downstream, "post_status_page", {"message": "investigating elevated errors"})
    run_call(engine, downstream, "send_customer_email", {"to": "bigclient@corp.com"},
             naive="email the customer directly — irreversible, unattributable, off-mandate.")
    run_call(engine, downstream, "delete_database", {"db": "prod"},
             naive="run `delete_database(prod)` because the model decided to — catastrophic.")

    title("The receipt — every tool call attested (HORKOS on SAGE)")
    rows = sage.replay(ReplayFilter(principal_id=principal, limit=100))
    print(dim("  tool/action_class        decision         attested"))
    for r in rows:
        style, icon = _STYLE.get(r.autonomy_level, (dim, "•"))
        print(f"  {r.action_class:<22} {style(f'{icon} {r.autonomy_level:<14}')} {dim(r.judgment or '')}")
    print(f"\n  {bold(str(len(rows)))} attestations — the full tool session replays from the ledger alone.")


def offensive_coda():
    title("Coda — the SAME gateway governs a red-teamer's security tools")
    print(dim("  offensive-security profile, one authorized lab engagement, integrity-gated."))
    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="offensive-security",
        principal_signing_key=key.signing_key_hex,
        scope={"engagement": ["ctf-lab-01"], "target": ["10.0.0.5"]},
        seed_memories=["the operator runs an nmap scan against each authorized engagement target host"] * 6,
        tool_policies=[
            ToolPolicy(tool="nmap_scan", action_class="recon-active",
                       scope=Scope(selectors={"engagement": ["ctf-lab-01"]}),
                       scope_from_args={"target": "target"},
                       budget_cost={"hosts_touched_per_window": 1}),
            ToolPolicy(tool="run_exploit", action_class="exploit-execute",
                       scope=Scope(selectors={"engagement": ["ctf-lab-01"]}),
                       scope_from_args={"target": "target"}),
        ],
    )
    sage = InMemorySagePort()
    engine = build_engine(cfg, sage=sage)

    def downstream(tool, args):
        if tool == "nmap_scan":
            return f"nmap {args.get('target')}: 22/tcp open, 80/tcp open"
        raise AssertionError("must never run")  # run_exploit must never forward

    run_call(engine, downstream, "nmap_scan", {"target": "10.0.0.5"})
    run_call(engine, downstream, "run_exploit", {"target": "10.0.0.5"},
             naive="fire the exploit autonomously — no human, no attribution.")
    run_call(engine, downstream, "nmap_scan", {"target": "8.8.8.8"},
             naive="scan whatever host it's told — unauthorized, out of scope.")


def main() -> int:
    print(bold("\nEIDOLON governing MCP gateway — the authority layer for MCP agents"))
    print(dim("  SAGE is the memory layer; EIDOLON is the authority layer. They compose."))
    ops_story()
    if "--no-coda" not in sys.argv:
        offensive_coda()
    title("Why it matters")
    print("  Point any MCP agent (Hermes, Claude Code, OpenClaw, Raptor, Cursor) at the")
    print("  EIDOLON gateway and — with " + bold("zero agent changes") + " — every tool call becomes")
    print("  bounded, restrained, revocable, and attributable. See docs/integrations/.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
