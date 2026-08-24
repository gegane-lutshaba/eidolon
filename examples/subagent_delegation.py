#!/usr/bin/env python
"""Twin → sub-agent delegation — attenuation that provably can't widen.

Hermes (and most agents) spawn sub-agents with "restricted toolsets" — but that
restriction is config. EIDOLON makes it a cryptographic, subset-only credential:
the twin attenuates its own delegation to a sub-agent, and the chain
root → twin → sub-agent is verified to root. The sub-agent can do a strict subset
and no more — even a widening attempt is rejected at attenuation time.

    uv run python examples/subagent_delegation.py
"""

from __future__ import annotations

import os
import sys

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.common.errors import AttenuationError
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

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code, t):  return f"\033[{code}m{t}\033[0m" if _COLOR else t
def bold(t):  return _c("1", t)
def dim(t):   return _c("2", t)
def green(t): return _c("32", t)
def amber(t): return _c("33", t)
def red(t):   return _c("31", t)


def main() -> int:
    profile = ProfileLoader().load("general-continuity")
    sage = InMemorySagePort()
    ada, twin, sub = crypto.generate_keypair(), crypto.generate_keypair(), crypto.generate_keypair()
    pid = ada.public_key_hex
    for _ in range(6):
        sage.observe(pid, "the principal answers atlas status and posts updates routinely", "memory", "docs.read")
    themis = Themis()
    kairos = Kairos(themis=themis, ethos=Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder()),
                    basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile, budget=BudgetLedger())
    certs = [Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                         ceiling=profile.default_ceiling(c)) for c in profile.class_names()]

    print(bold("\nTwin → sub-agent delegation (subset-only)\n"))

    # Ada → twin: the full mandate.
    root = themis.mint(ada.signing_key_hex, MintParams(
        principal_id=pid, issued_to=twin.public_key_hex,
        scope={"project": ["atlas", "borealis"], "channel": ["#eng"]},
        exclusions=list(profile.mandate_schema.exclusion_types),
        permitted_classes=["answer-status", "retrieve-context", "draft-comm", "post-status"],
        escalation_required=["commit-action"], window=Window(),
        blast_radius_budget={"posts_per_window": 5, "scope_expansion": 0},
        max_autonomy="autonomous", revocation=Revocation(), nonce="root"))
    print(f"  Ada → twin: classes={dim('answer, retrieve, draft, post')}, "
          f"scope={dim('atlas+borealis')}, autonomy={dim('autonomous')}")

    # Twin → sub-agent: a strict subset (read-only, one project).
    child = themis.attenuate(root, MintParams(
        principal_id=pid, issued_to=sub.public_key_hex,
        scope={"project": ["atlas"]},  # narrower
        exclusions=list(profile.mandate_schema.exclusion_types),
        permitted_classes=["answer-status"],  # narrower
        escalation_required=["commit-action"], window=Window(),
        blast_radius_budget={"posts_per_window": 1, "scope_expansion": 0},
        max_autonomy="notify", nonce="child"), twin.signing_key_hex)
    print(f"  twin → sub-agent: classes={dim('answer only')}, scope={dim('atlas only')}, autonomy={dim('notify')}")
    print(dim(f"  chain: root {root.id[:10]}… → child {child.id[:10]}…  (verifies to root)\n"))

    chain = [root, child]

    def act(cls, desc, project="atlas"):
        a = Action(id=cls, action_class=cls, description=desc, scope=Scope(selectors={"project": [project]}))
        ctx = Context(principal_id=pid, query=desc)
        d = kairos.resolve(a, ctx, chain, certs)
        style = green if d.level.value in ("AUTONOMOUS_ACT", "NOTIFY_ACT") else (
            red if d.level.value == "DENY" else amber)
        print(f"  sub-agent: {desc:<42} → {style(d.level.value)}")

    # In-subset: answer status on atlas → acts.
    act("answer-status", "answer atlas status question")
    # Out-of-subset class: draft-comm (twin has it, sub-agent doesn't) → denied.
    act("draft-comm", "draft an atlas email")
    # Out-of-subset scope: borealis (twin has it, sub-agent doesn't) → denied.
    act("answer-status", "answer borealis status", project="borealis")

    # A widening attenuation is rejected at creation.
    print()
    try:
        themis.attenuate(root, MintParams(
            principal_id=pid, issued_to=sub.public_key_hex, scope={"project": ["atlas"]},
            exclusions=[], permitted_classes=["commit-action"],  # widens: new class + drops exclusions
            escalation_required=["commit-action"], window=Window(),
            blast_radius_budget={"scope_expansion": 0}, max_autonomy="autonomous", nonce="bad"),
            twin.signing_key_hex)
    except AttenuationError as exc:
        print(f"  {red('widening rejected')}: {exc}")

    print(dim("\n  A sub-agent's authority is a cryptographic subset of the twin's — provably,"))
    print(dim("  not by configuration. The standard, biscuit-exportable form (docs/standards-interop.md).\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
