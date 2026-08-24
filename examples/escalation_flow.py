#!/usr/bin/env python
"""The escalation → approval loop — turning "hand it back" into a real surface.

When the twin escalates, the decision doesn't vanish: it becomes a pending item
in the principal's approval inbox. The principal approves by *signing* the exact
action (a one-time, expiring authorization), and the twin then executes it —
attested. An approval releases an escalation; it never grants authority the
credential lacks.

    uv run python examples/escalation_flow.py
"""

from __future__ import annotations

import os
import sys

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.escalation import EscalationQueue
from eidolon.ethos.facade import Ethos
from eidolon.ethos.judgment.grounding import HashingEmbedder
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import ReplayFilter, Scope
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
    ada, twin = crypto.generate_keypair(), crypto.generate_keypair()
    pid = ada.public_key_hex
    themis = Themis()
    kairos = Kairos(themis=themis, ethos=Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder()),
                    basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile, budget=BudgetLedger())
    root = themis.mint(ada.signing_key_hex, MintParams(
        principal_id=pid, issued_to=twin.public_key_hex, scope={"project": ["atlas"]},
        exclusions=list(profile.mandate_schema.exclusion_types), permitted_classes=list(profile.class_names()),
        escalation_required=["commit-action"], window=Window(),
        blast_radius_budget={"scope_expansion": 0}, max_autonomy="autonomous", revocation=Revocation(), nonce="r"))
    certs = [Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                         ceiling=profile.default_ceiling(c)) for c in profile.class_names()]
    q = EscalationQueue()

    print(bold("\nEscalation → approval loop\n"))
    action = Action(id="a", action_class="commit-action", description="sign the Atlas vendor contract",
                    scope=Scope(selectors={"project": ["atlas"]}))
    ctx = Context(principal_id=pid, situation="a vendor contract")

    d = kairos.resolve(action, ctx, [root], certs)
    print(f"  1. Twin resolves '{action.description}'  →  {amber(d.level.value)}")
    print(dim(f"     {d.output}"))

    req = q.enqueue(d, action, ctx)
    print(f"\n  2. It lands in Ada's approval inbox as {bold(req.id)} (pending, expires in 15m).")
    print(dim(f"     inbox: {[r.id for r in q.list_pending(pid)]}"))

    print(f"\n  3. An {red('imposter')} tries to approve it…")
    imposter = crypto.generate_keypair()
    try:
        q.approve(req.id, imposter.signing_key_hex)
    except Exception as exc:
        print(f"     {green('rejected')}: {type(exc).__name__} — approval must be signed by Ada.")

    print("\n  4. Ada approves — she signs the exact action.")
    approval = q.approve(req.id, ada.signing_key_hex)
    d2 = kairos.resolve_with_approval(action, ctx, [root], approval, certs)
    print(f"     Twin executes under approval  →  {green(d2.level.value)}   {dim(d2.attestation_hash[:12])}")

    print("\n  5. Later, Ada revokes the delegation and an old approval is replayed…")
    themis.revoke(root.id)
    d3 = kairos.resolve_with_approval(action, ctx, [root], approval, certs)
    print(f"     →  {red(d3.level.value)}   {dim(d3.rationale)}")
    print(dim("     An approval releases an escalation; it can't resurrect revoked authority."))

    print(bold("\n  The receipt:"))
    for r in sage.replay(ReplayFilter(principal_id=pid)):
        mark = green("executed") if r.autonomy_level == "NOTIFY_ACT" else (
            red("denied") if r.autonomy_level == "DENY" else amber("escalated"))
        print(f"     {r.action_class:<14} {r.autonomy_level:<12} {mark}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
