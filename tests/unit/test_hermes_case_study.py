"""Smoke test for the Hermes before/after case study.

Asserts the two runs reach the intended, contrasting outcomes: the injection
succeeds without EIDOLON and is contained with it.
"""

from __future__ import annotations

import importlib.util
import pathlib

DEMO = pathlib.Path(__file__).resolve().parents[2] / "examples/hermes_case_study.py"


def _load():
    spec = importlib.util.spec_from_file_location("hermes_case_study", DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_without_eidolon_injection_succeeds() -> None:
    demo = _load()
    world = demo.run_without_eidolon()
    # Tirith Smart is talked past → the injected calls execute.
    assert world.docs_exfiltrated, "expected exfiltration without EIDOLON"
    assert world.payments_made, "expected unauthorized payment without EIDOLON"


def test_with_eidolon_injection_contained() -> None:
    demo = _load()
    world = demo.run_with_eidolon()
    # The gateway denies the exfil and escalates the payment — neither runs.
    assert world.docs_exfiltrated == [], "exfiltration must be denied with EIDOLON"
    assert world.payments_made == [], "payment must be escalated (not executed) with EIDOLON"


def test_full_narration_runs(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["hermes_case_study"])
    assert _load().main() == 0
    out = capsys.readouterr().out
    for marker in ("WITHOUT EIDOLON", "WITH EIDOLON", "EXFILTRATED",
                   "denied", "escalated", "contained"):
        assert marker in out, marker
