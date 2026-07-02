"""Aspirational-self / coaching acceptance (PRD §2.2, §12 — v2).

The load-bearing property is DECOUPLING: the coaching layer reads ETHOS version
diffs + the attestation ledger, but nothing in the decision path imports it, and
running the coach changes zero live decisions.
"""

from __future__ import annotations

import ast
import datetime as _dt
import pathlib

import pytest

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.coaching import Aspiration, Coach
from eidolon.coaching.types import ClassTarget
from eidolon.common import crypto
from eidolon.ethos.facade import Ethos
from eidolon.ethos.versioning import snapshot
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import DecisionLevel
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Attestation, ReplayFilter, Scope
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window
from eidolon.types import Action, Context

SRC = pathlib.Path(__file__).resolve().parents[2] / "src/eidolon"
DECISION_PATH = ["ethos/judgment", "themis", "kairos"]


def _imports(pyfile: pathlib.Path) -> set[str]:
    tree = ast.parse(pyfile.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_decision_path_never_imports_coaching() -> None:
    offenders = {}
    for rel in DECISION_PATH:
        for pyfile in (SRC / rel).rglob("*.py"):
            bad = {i for i in _imports(pyfile) if "coaching" in i}
            if bad:
                offenders[str(pyfile)] = bad
    assert not offenders, f"decision path imports coaching: {offenders}"


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


def _att(cls, level, conf=0.9, escalated=False) -> Attestation:
    return Attestation(
        action=f"do {cls}", action_class=cls,
        timestamp=_dt.datetime(2026, 7, 2, tzinfo=_dt.UTC),
        autonomy_level=level, confidence=conf, would_have_escalated=escalated,
        principal_id="p",
    )


def test_behavior_summary_from_ledger() -> None:
    atts = [
        _att("answer-status", "AUTONOMOUS_ACT", 0.9),
        _att("answer-status", "AUTONOMOUS_ACT", 0.8),
        _att("draft-comm", "ESCALATE", 0.4, escalated=True),
    ]
    summ = {b.action_class: b for b in Coach().summarize_behavior(atts)}
    assert summ["answer-status"].decisions == 2
    assert summ["answer-status"].acted == 2
    assert summ["draft-comm"].escalations == 1
    assert summ["draft-comm"].escalation_rate == 1.0


def test_under_escalation_flagged() -> None:
    # Principal aspires to escalate draft-comm ~50% but never does.
    atts = [_att("draft-comm", "DRAFT", 0.9) for _ in range(4)]
    asp = Aspiration(principal_id="p", targets=[
        ClassTarget(action_class="draft-comm", target_escalation_rate=0.5)])
    report = Coach().coach(asp, atts)
    assert any(n.topic == "under-escalating" and n.severity == "flag" for n in report.notes)


def test_acting_on_thin_confidence_flagged() -> None:
    atts = [_att("post-status", "NOTIFY_ACT", 0.55) for _ in range(3)]
    asp = Aspiration(principal_id="p", targets=[
        ClassTarget(action_class="post-status", min_confidence_to_act=0.8)])
    report = Coach().coach(asp, atts)
    assert any(n.topic == "acting-on-thin-confidence" for n in report.notes)


def test_ethos_drift_surfaced() -> None:
    a = snapshot({"engine": "JudgmentEngine", "version": "v0"})
    b = snapshot({"engine": "JudgmentEngine", "version": "v1", "threshold": 0.8})
    asp = Aspiration(principal_id="p")
    report = Coach().coach(asp, [], snapshots=(a, b))
    assert report.drift is not None and report.drift.drifted
    assert any(n.topic == "policy-drift" for n in report.notes)


def test_coaching_does_not_change_decisions(profile) -> None:
    # Behavioral isolation: resolving with vs without ever invoking the coach
    # yields identical decisions.
    def build():
        sage = InMemorySagePort()
        principal = crypto.generate_keypair()
        twin = crypto.generate_keypair()
        pid = principal.public_key_hex
        for _ in range(5):
            sage.observe(pid, "principal reports atlas status friday on track weekly", "memory", "docs.read")
        themis = Themis()
        kairos = Kairos(themis=themis, ethos=Ethos(sage, style=None, profile=profile),
                        basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile)
        root = themis.mint(principal.signing_key_hex, MintParams(
            principal_id=pid, issued_to=twin.public_key_hex, scope={"project": ["atlas"]},
            exclusions=list(profile.mandate_schema.exclusion_types),
            permitted_classes=list(profile.class_names()), escalation_required=["commit-action"],
            window=Window(), blast_radius_budget={"scope_expansion": 0},
            max_autonomy="autonomous", revocation=Revocation(), nonce="r"))
        certs = [Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                             ceiling=profile.default_ceiling(c)) for c in profile.class_names()]
        return sage, kairos, pid, root, certs

    action = Action(id="a", action_class="answer-status",
                    description="answer atlas status friday on track weekly",
                    scope=Scope(selectors={"project": ["atlas"]}))

    sage1, k1, pid1, root1, certs1 = build()
    ctx1 = Context(principal_id=pid1, query="answer atlas status friday on track weekly")
    d_plain = k1.resolve(action, ctx1, [root1], certs1)

    sage2, k2, pid2, root2, certs2 = build()
    ctx2 = Context(principal_id=pid2, query="answer atlas status friday on track weekly")
    d_before = k2.resolve(action, ctx2, [root2], certs2)
    # Run the coach against the ledger between resolves — must not perturb anything.
    Coach().coach(
        Aspiration(principal_id=pid2, targets=[ClassTarget(action_class="answer-status", target_escalation_rate=0.9)]),
        k2._horkos.replay(ReplayFilter(principal_id=pid2)),
    )
    d_after = k2.resolve(action, ctx2, [root2], certs2)

    assert d_plain.level == d_before.level == d_after.level == DecisionLevel.AUTONOMOUS_ACT
