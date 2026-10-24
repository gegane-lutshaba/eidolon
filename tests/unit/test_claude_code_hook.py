"""The stdlib Claude Code hook: fail-closed by default (known-issue #4)."""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys

HOOK = pathlib.Path(__file__).resolve().parents[2] / "integrations/claude_code/eidolon_hook.py"
PRE = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
       "tool_input": {"command": "ls"}, "cwd": "/tmp"}


def _dead_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens here now
    return f"http://127.0.0.1:{port}"


def _run(payload: dict | str, **env: str) -> tuple[int, str]:
    full = {k: v for k, v in os.environ.items() if not k.startswith("EIDOLON_")}
    full.update({"EIDOLON_URL": _dead_url(), "EIDOLON_HOOK_TIMEOUT": "1", **env})
    data = payload if isinstance(payload, str) else json.dumps(payload)
    r = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True,
                       text=True, env=full, timeout=20)
    return r.returncode, r.stdout


def _decision(out: str) -> str | None:
    if not out.strip():
        return None  # silent = allow
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def test_unreachable_gate_denies_by_default() -> None:
    code, out = _run(PRE, EIDOLON_AGENT_KEY="egk_x")
    assert code == 0 and _decision(out) == "deny"


def test_missing_key_denies_by_default() -> None:
    _code, out = _run(PRE)
    assert _decision(out) == "deny"


def test_unreadable_payload_denies_by_default() -> None:
    _code, out = _run("not json", EIDOLON_AGENT_KEY="egk_x")
    assert _decision(out) == "deny"


def test_fail_open_is_an_explicit_opt_out() -> None:
    _code, out = _run(PRE, EIDOLON_AGENT_KEY="egk_x", EIDOLON_HOOK_STRICT="0")
    assert _decision(out) is None


def test_post_tool_use_never_blocks() -> None:
    post = {"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_response": "x"}
    _code, out = _run(post, EIDOLON_AGENT_KEY="egk_x")
    assert _decision(out) is None
