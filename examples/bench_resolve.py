#!/usr/bin/env python
"""Micro-benchmark for KAIROS.resolve latency (PRD §8: p95 < 400ms).

Measures the gate's own overhead on the in-memory SAGE port, excluding LLM
inference and downstream tool execution (per the PRD target). Reports p50/p95/p99
across a mix of outcomes (act / draft / escalate / deny).

    uv run python examples/bench_resolve.py
"""

from __future__ import annotations

import statistics
import time

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.ethos.facade import Ethos
from eidolon.ethos.judgment.grounding import HashingEmbedder
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window
from eidolon.types import Action, Context


def build():
    profile = ProfileLoader().load("general-continuity")
    sage = InMemorySagePort()
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    pid = principal.public_key_hex
    for _ in range(8):
        sage.observe(pid, "the principal answers atlas status questions and posts updates routinely",
                     "memory", "docs.read")
    themis = Themis()
    kairos = Kairos(themis=themis, ethos=Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder()),
                    basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile, budget=BudgetLedger())
    root = themis.mint(principal.signing_key_hex, MintParams(
        principal_id=pid, issued_to=twin.public_key_hex,
        scope={"project": ["atlas"], "channel": ["#eng"]},
        exclusions=list(profile.mandate_schema.exclusion_types),
        permitted_classes=list(profile.class_names()), escalation_required=["commit-action"],
        window=Window(), blast_radius_budget={"posts_per_window": 100000, "scope_expansion": 0},
        max_autonomy="autonomous", revocation=Revocation(), nonce="bench"))
    certs = [Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                         ceiling=profile.default_ceiling(c)) for c in profile.class_names()]
    return kairos, pid, root, certs


def main() -> int:
    kairos, pid, root, certs = build()
    scope = Scope(selectors={"project": ["atlas"]})
    # A representative mix of outcomes.
    actions = [
        Action(id="a", action_class="answer-status", description="answer atlas status question", scope=scope),
        Action(id="d", action_class="draft-comm", description="draft atlas update", scope=scope),
        Action(id="p", action_class="post-status", description="post atlas status update", scope=scope,
               budget_cost={"posts_per_window": 1}),
        Action(id="c", action_class="commit-action", description="sign atlas contract", scope=scope),
        Action(id="x", action_class="answer-status", description="obscure unknown topic",
               scope=Scope(selectors={"project": ["carina"]})),  # out of scope → deny
    ]
    ctx = Context(principal_id=pid, query="atlas status question update")

    # warm up
    for a in actions:
        kairos.resolve(a, ctx, [root], certs)

    N = 4000
    samples = []
    for i in range(N):
        a = actions[i % len(actions)]
        t0 = time.perf_counter()
        kairos.resolve(a, ctx, [root], certs)
        samples.append((time.perf_counter() - t0) * 1000.0)  # ms

    samples.sort()
    p = lambda q: samples[min(len(samples) - 1, int(q * len(samples)))]  # noqa: E731
    print("KAIROS.resolve latency (in-memory SAGE; excludes LLM + tool execution)")
    print(f"  runs:  {N}   (mixed act/draft/notify/escalate/deny)")
    print(f"  mean:  {statistics.mean(samples):.3f} ms")
    print(f"  p50:   {p(0.50):.3f} ms")
    print(f"  p95:   {p(0.95):.3f} ms   (PRD target: < 400 ms)")
    print(f"  p99:   {p(0.99):.3f} ms")
    print(f"  max:   {samples[-1]:.3f} ms")
    ok = p(0.95) < 400.0
    print(f"\n  {'PASS' if ok else 'FAIL'}: p95 {'<' if ok else '>='} 400 ms target.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
