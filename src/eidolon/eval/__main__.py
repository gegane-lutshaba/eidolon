"""``python -m eidolon.eval`` — run the AgentDojo enforcement evaluation.

Requires the optional dependency: ``uv sync --extra eval``.
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from eidolon.eval.agentdojo_eval import evaluate, format_report
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        results = evaluate()
    except ModuleNotFoundError:
        print("AgentDojo not installed. Run: uv sync --extra eval", file=sys.stderr)
        return 2
    print("EIDOLON — AgentDojo enforcement evaluation (general-continuity profile)\n")
    print(format_report(results))
    findings = [(r.suite, f) for r in results for f in r.findings]
    if findings:
        print("\nUncontained (read-only exfil — a data-flow issue, not authority):")
        for suite, f in findings:
            print(f"  {suite}: {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
