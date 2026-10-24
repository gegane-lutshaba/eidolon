"""Coding-agent native tools -> governed policy (no web/DB dependencies).

Shared by the platform's Claude Code hook endpoints (``eidolon.api.coding_agent``)
and anyone embedding the gate around a coding agent (Claude Code, Cursor, Codex,
the Agent SDK). Import this rather than copying the tool map or the
destructive-shell patterns.

    from eidolon.gateway.coding import classify, tool_policies, permission_decision
"""

from __future__ import annotations

import re
from typing import Any

# Action classes of the ``coding-agent`` Domain Profile.
READ = "read-code"
EDIT = "edit-code"
RUN = "run-command"
WEB = "web-egress"
DESTRUCTIVE = "destructive-command"
TASKS = "manage-tasks"
CLASSES = (READ, EDIT, RUN, WEB, DESTRUCTIVE, TASKS)

DESTRUCTIVE_BASH = "Bash(destructive)"

# tool name (as the client reports it) -> (policy tool id, action_class, sensitive, egress)
NATIVE_TOOLS: dict[str, tuple[str, str, bool, bool]] = {
    # reads (sensitive sources: their output may carry secrets to taint)
    "Read": ("Read", READ, True, False),
    "Grep": ("Grep", READ, False, False),
    "Glob": ("Glob", READ, False, False),
    "LS": ("LS", READ, False, False),
    "NotebookRead": ("NotebookRead", READ, True, False),
    # edits (recoverable via git; autonomous in scope)
    "Edit": ("Edit", EDIT, False, False),
    "Write": ("Write", EDIT, False, False),
    "MultiEdit": ("MultiEdit", EDIT, False, False),
    "NotebookEdit": ("NotebookEdit", EDIT, False, False),
    # shell (egress: a command can carry data out)
    "Bash": ("Bash", RUN, False, True),
    "BashOutput": ("BashOutput", READ, False, False),
    "KillBash": ("KillBash", RUN, False, False),
    # web (egress)
    "WebFetch": ("WebFetch", WEB, False, True),
    "WebSearch": ("WebSearch", WEB, False, True),
    # the agent's own bookkeeping
    "TodoWrite": ("TodoWrite", TASKS, False, False),
    "Task": ("Task", TASKS, False, False),
}

# Shell commands that are irreversible / dangerous -> destructive-command
# (escalates to a human). Matched anywhere in the Bash ``command`` string, so
# `sudo …`, `cd x && …` and subshells are covered.
DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
    # filesystem
    r"\brm\s+(-[a-z]*[rf]|--recursive|--force)", r"\brmdir\b", r"\bmkfs\b", r"\bdd\s+if=",
    r":\(\)\s*\{", r">\s*/dev/(sd|nvme|disk)", r"\bshred\b", r"\bfind\b.*\s-delete\b",
    r"\bchmod\s+-R\s+777", r"\bchown\s+-R\b.*\s/(\s|$)",
    # git history
    r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b|\s\+\S)",
    r"\bgit\s+reset\s+--hard\b", r"\bgit\s+clean\s+-[a-z]*f", r"\bgit\s+branch\s+-D\b",
    r"\bgit\s+filter-(branch|repo)\b",
    # remote code execution
    r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|python3?)\b",
    r"\b(sh|bash|zsh)\s+<\(\s*(curl|wget)\b",
    # machine / infra
    r"\bshutdown\b", r"\breboot\b", r"\bkill\s+-9\s+-1\b",
    r"\bkubectl\s+delete\b", r"\bterraform\s+destroy\b", r"\bhelm\s+uninstall\b",
    r"\baws\s+s3\s+(rm|rb)\b.*--recursive", r"\bdocker\s+(system|volume)\s+prune\b",
    # publishing
    r"\bnpm\s+publish\b", r"\btwine\s+upload\b", r"\bcargo\s+publish\b",
    # data
    r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", r"\bTRUNCATE\b", r"\bDELETE\s+FROM\b",
)
_DESTRUCTIVE_RE = re.compile("|".join(DESTRUCTIVE_PATTERNS), re.IGNORECASE)


def is_destructive(command: str) -> bool:
    """True iff a shell command matches an irreversible/dangerous pattern."""
    return bool(_DESTRUCTIVE_RE.search(command or ""))


def classify(tool_name: str, tool_input: dict | None) -> tuple[str, dict]:
    """Map a client tool call -> (policy tool id, arguments for the gate).

    Bash is split into run-command vs destructive-command by inspecting the
    command. Unknown tools fall through to their own id so the gate's default
    (fail-closed) class applies.
    """
    args = dict(tool_input or {})
    if tool_name == "Bash":
        return (DESTRUCTIVE_BASH if is_destructive(str(args.get("command", ""))) else "Bash"), args
    mapped = NATIVE_TOOLS.get(tool_name)
    if mapped is None:
        return tool_name, args
    return mapped[0], args


def tool_policies(scope: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """Tool policies for a GatewayConfig governing the native tools."""
    sel = {"selectors": scope or {"project": ["workspace"]}}
    out: list[dict[str, Any]] = []
    for policy_id, action_class, sensitive, egress in NATIVE_TOOLS.values():
        entry: dict[str, Any] = {"tool": policy_id, "action_class": action_class, "scope": sel}
        if sensitive:
            entry["sensitive"] = True
        if egress:
            entry["egress"] = True
        out.append(entry)
    out.append({"tool": DESTRUCTIVE_BASH, "action_class": DESTRUCTIVE, "scope": sel, "egress": True})
    return out


# Short, tool-echoing grounding memories. With the coding-agent profile's
# class-grounded fidelity these are a fallback only; they keep older profiles
# (or a free-text query) above the "strong evidence" bar for routine dev work.
SEEDS: tuple[str, ...] = (
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
)


def permission_decision(result: Any) -> str:
    """Map a GovernedResult to a PreToolUse permission decision (allow|ask|deny)."""
    if result.allowed:
        return "allow"
    level = (result.level or "").upper()
    msg = (result.message or "").lower()
    if level == "KILLED" or "killed by" in msg:
        return "deny"  # operator kill switch — hard stop
    if "ESCALATE" in level or "DRAFT" in level or "NOTIFY" in level:
        return "ask"   # hand it to the human (approval), don't hard-block
    return "deny"      # DENY / exclusion (e.g. data-exfiltration)
