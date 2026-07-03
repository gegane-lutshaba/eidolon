"""Smoke test for the gateway showcase demo so it can't bit-rot."""

from __future__ import annotations

import importlib.util
import pathlib

DEMO = pathlib.Path(__file__).resolve().parents[2] / "examples/mcp_gateway_demo.py"


def _load():
    spec = importlib.util.spec_from_file_location("mcp_gateway_demo", DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gateway_demo_runs(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["mcp_gateway_demo"])
    assert _load().main() == 0
    out = capsys.readouterr().out
    for marker in ("AUTONOMOUS_ACT", "DRAFT", "NOTIFY_ACT", "DENY", "ESCALATE",
                   "REAL TOOL RAN", "tool NOT called", "attested"):
        assert marker in out, marker
