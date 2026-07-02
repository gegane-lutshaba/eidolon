"""Live-SAGE acceptance (PRD §6.1, §6.5).

Run with: ``make up && make test-integration``.
- cross-principal isolation on the live consensus store;
- attest -> ledger_hash -> replay byte-identical from the live ledger;
- full engagement replay reconstructable from replay alone;
- end-to-end KAIROS path per capability class, one attestation each.
"""

from __future__ import annotations

import datetime as _dt
import time
import uuid

import pytest

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.ethos.facade import Ethos
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger, DecisionLevel
from eidolon.profile import ProfileLoader
from eidolon.sage.port import Attestation, ReplayFilter, Scope
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window
from eidolon.types import Action, Context

pytestmark = pytest.mark.integration


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _wait_until(predicate, *, timeout: float = 20.0, interval: float = 2.0):
    """Poll until BFT consensus commits the write (or time out)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def test_cross_principal_isolation_live(live_sage) -> None:
    a = f"principal-A-{_uid()}"
    b = f"principal-B-{_uid()}"
    marker = f"roadmap-secret-{_uid()}"
    live_sage.observe(a, f"{marker} for atlas", "memory", "docs.read")
    live_sage.observe(b, "unrelated content", "memory", "docs.read")

    # Wait until A's write commits (so the isolation check is meaningful), then
    # confirm B still cannot see it.
    _wait_until(lambda: any(marker in m.content for m in live_sage.recall(a, Scope(), marker, k=20)))
    b_recall = live_sage.recall(b, Scope(), marker, k=20)
    assert all(marker not in m.content for m in b_recall)


def test_attest_replay_byte_identical_live(live_sage) -> None:
    principal = f"principal-{_uid()}"
    record = Attestation(
        action="post status update",
        action_class="post-status",
        timestamp=_dt.datetime(2026, 7, 2, 12, 0, tzinfo=_dt.UTC),
        delegation_chain=["root", "twin"],
        evidence_refs=["mem-1"],
        ethos_version="v0",
        judgment="PROCEED",
        confidence=0.9,
        autonomy_level="NOTIFY_ACT",
        principal_id=principal,
    )
    ledger_hash = live_sage.attest(record)
    assert ledger_hash

    match = _wait_until(
        lambda: [r for r in live_sage.replay(ReplayFilter(principal_id=principal))
                 if r.action_class == "post-status"]
    )
    assert match
    # Byte-identity: the replayed record reproduces the original exactly.
    from eidolon.common.canonical import canonical_json

    assert canonical_json(match[0]) == canonical_json(record)


def test_full_engagement_replay_and_gate_live(live_sage) -> None:
    profile = ProfileLoader().load("general-continuity")
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    # Namespace principal ids by pubkey so isolation holds on the shared node.
    pid = principal.public_key_hex

    for _ in range(5):
        live_sage.observe(pid, "principal reports atlas status friday on track weekly", "memory", "docs.read")
    # Wait for the evidence to commit so the twin has grounding to act on.
    _wait_until(
        lambda: len(live_sage.recall(pid, Scope(selectors={"project": ["atlas"]}),
                                     "atlas status friday on track weekly", k=8)) >= 3
    )

    themis = Themis()
    kairos = Kairos(
        themis=themis,
        ethos=Ethos(live_sage, style=None, profile=profile),
        basanos=Basanos(),
        horkos=Horkos(live_sage),
        sage=live_sage,
        profile=profile,
        budget=BudgetLedger(),
    )
    root = themis.mint(
        principal.signing_key_hex,
        MintParams(
            principal_id=pid,
            issued_to=twin.public_key_hex,
            scope={"project": ["atlas"], "channel": ["#eng"]},
            exclusions=list(profile.mandate_schema.exclusion_types),
            permitted_classes=list(profile.class_names()),
            escalation_required=["commit-action"],
            window=Window(),
            blast_radius_budget={"posts_per_window": 5, "scope_expansion": 0},
            max_autonomy="autonomous",
            revocation=Revocation(),
            nonce=_uid(),
        ),
    )
    certs = [
        Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                    ceiling=profile.default_ceiling(c))
        for c in profile.class_names()
    ]

    def resolve(cls, desc, budget_cost=None):
        action = Action(id=_uid(), action_class=cls, description=desc,
                        scope=Scope(selectors={"project": ["atlas"]}),
                        budget_cost=budget_cost or {})
        ctx = Context(principal_id=pid, query=desc, situation=desc)
        return kairos.resolve(action, ctx, [root], certs)

    d_answer = resolve("answer-status", "answer atlas status friday on track weekly")
    d_draft = resolve("draft-comm", "draft atlas status friday on track weekly note")
    d_post = resolve("post-status", "post atlas status friday on track weekly", {"posts_per_window": 1})
    d_commit = resolve("commit-action", "sign the atlas vendor contract")

    assert d_answer.level == DecisionLevel.AUTONOMOUS_ACT
    assert d_draft.level == DecisionLevel.DRAFT
    assert d_post.level == DecisionLevel.NOTIFY_ACT
    assert d_commit.level == DecisionLevel.ESCALATE

    # Every resolve produced exactly one attestation, all replayable from the
    # live ledger alone (poll until the four attestations commit).
    def all_four() -> bool:
        classes = [r.action_class for r in live_sage.replay(ReplayFilter(principal_id=pid, limit=1000))]
        return all(cls in classes for cls in
                   ("answer-status", "draft-comm", "post-status", "commit-action"))

    assert _wait_until(all_four, timeout=30.0), "not all attestations committed to the live ledger"
