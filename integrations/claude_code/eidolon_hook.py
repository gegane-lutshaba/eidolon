#!/usr/bin/env python3
"""EIDOLON hook for Claude Code — govern EVERY native tool call.

An MCP gateway only sees `tools/call`; it is blind to Claude Code's built-in
Bash / Edit / Write / Read. This hook closes that gap. Wire it as BOTH a
PreToolUse and a PostToolUse hook (see integrations/claude_code/README.md):

- PreToolUse  -> POST /gate/evaluate : KAIROS rules allow | ask | deny, attests,
                 and the call shows up in mission control. A `deny`/`ask` is fed
                 back to Claude Code as a permission decision.
- PostToolUse -> POST /gate/observe  : the tool's output is fed to the taint
                 tracker, so a later egress (shell/web) carrying a secret it
                 revealed is caught as data-exfiltration.

Zero dependencies (stdlib only). Configure via environment:

    EIDOLON_URL         base URL (default https://eidolon.onyxcreator.com)
    EIDOLON_AGENT_KEY   the agent's egk_ gateway key (required)
    EIDOLON_HOOK_STRICT if "1", fail CLOSED when the gate is unreachable
                        (default: fail open, so an outage never blocks work)
    EIDOLON_HOOK_TIMEOUT seconds to wait for the gate (default 5)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("EIDOLON_URL", "https://eidolon.onyxcreator.com").rstrip("/")
KEY = os.environ.get("EIDOLON_AGENT_KEY", "")
STRICT = os.environ.get("EIDOLON_HOOK_STRICT") == "1"
TIMEOUT = float(os.environ.get("EIDOLON_HOOK_TIMEOUT", "5"))


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{URL}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json",
                 "authorization": f"Bearer {KEY}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (trusted host)
        return json.loads(r.read().decode())


def _allow() -> None:
    # Silent allow: no decision override, exit clean.
    sys.exit(0)


def _emit_pre(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,               # allow | ask | deny
        "permissionDecisionReason": f"EIDOLON: {reason}" if reason else "EIDOLON",
    }}))
    sys.exit(0)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — never crash the agent on bad input
        _allow()
    event = payload.get("hook_event_name", "")
    tool = payload.get("tool_name", "")

    if not KEY:
        sys.stderr.write("EIDOLON hook: EIDOLON_AGENT_KEY not set — passing through.\n")
        _allow()

    if event == "PostToolUse":
        # Feed outputs to the taint tracker; never blocks.
        try:
            out = payload.get("tool_response", "")
            _post("/gate/observe", {"tool": tool, "output": json.dumps(out)[:20000]})
        except Exception:  # noqa: BLE001
            pass
        _allow()

    # PreToolUse (default): ask the gate.
    try:
        verdict = _post("/gate/evaluate", {
            "tool": tool, "tool_input": payload.get("tool_input", {}),
            "cwd": payload.get("cwd", ""),
        })
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if STRICT:
            _emit_pre("deny", f"gate unreachable ({exc}); failing closed")
        sys.stderr.write(f"EIDOLON hook: gate unreachable ({exc}); allowing (set EIDOLON_HOOK_STRICT=1 to block).\n")
        _allow()
    except Exception as exc:  # noqa: BLE001
        if STRICT:
            _emit_pre("deny", f"gate error ({exc}); failing closed")
        _allow()

    decision = verdict.get("decision", "allow")
    reason = verdict.get("reason") or verdict.get("level", "")
    if decision == "allow":
        _allow()
    _emit_pre(decision, reason)


if __name__ == "__main__":
    main()
