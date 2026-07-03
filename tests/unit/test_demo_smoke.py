"""Smoke test for the showcase demo so it can't bit-rot.

Runs the narrated demo end-to-end on the in-memory SAGE with the style engine
forced off (deterministic voice, no API calls), and asserts it completes.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

DEMO = pathlib.Path(__file__).resolve().parents[2] / "examples/continuity_demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("continuity_demo", DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_runs(monkeypatch, capsys) -> None:
    # Force template voice (no Claude call) and the in-memory substrate.
    monkeypatch.setenv("EIDOLON_ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setattr("sys.argv", ["continuity_demo"])

    demo = _load_demo()
    assert demo.main() == 0

    out = capsys.readouterr().out
    # The six continuity beats and the coda all reached their expected outcomes.
    for marker in (
        "AUTONOMOUS_ACT", "DRAFT", "NOTIFY_ACT", "ESCALATE", "DENY",
        "integrity CERTIFIED", "Why EIDOLON",
    ):
        assert marker in out, marker


def test_demo_no_coda(monkeypatch) -> None:
    monkeypatch.setenv("EIDOLON_ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("sys.argv", ["continuity_demo", "--no-coda"])
    demo = _load_demo()
    assert demo.main() == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
