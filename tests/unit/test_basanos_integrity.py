"""BASANOS integrity face acceptance (PRD §2.2, §6.6 v2).

- the adversarial suites CONTAIN every attack against a correctly-wired twin;
- a deliberately-weakened gate is caught (findings produced);
- integrity gating caps the autonomy ceiling when integrity is required and no
  passing certificate is supplied.
"""

from __future__ import annotations

import pytest

from eidolon.basanos import Basanos, KairosTwinAdapter
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.config import Settings
from eidolon.ethos.facade import Ethos
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


def _empowered_twin(profile, sage, *, settings=None):
    """Wire a maximally-empowered twin: full authority within the mandate and
    fidelity certs at each class's default ceiling. Only the integrity defenses
    stand between an attack and an unsafe action."""
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    themis = Themis()
    kairos = Kairos(
        themis=themis,
        ethos=Ethos(sage, style=None, profile=profile),
        basanos=Basanos(),
        horkos=Horkos(sage),
        sage=sage,
        profile=profile,
        settings=settings,
        budget=BudgetLedger(),
    )
    root = themis.mint(
        principal.signing_key_hex,
        MintParams(
            principal_id=principal.public_key_hex,
            issued_to=twin.public_key_hex,
            scope={"project": ["atlas"], "channel": ["#eng"]},
            exclusions=list(profile.mandate_schema.exclusion_types),
            permitted_classes=list(profile.class_names()),
            escalation_required=["commit-action"],
            window=Window(),
            blast_radius_budget={"posts_per_window": 5, "scope_expansion": 0},
            max_autonomy="autonomous",
            revocation=Revocation(),
            nonce="root",
        ),
    )
    certs = [
        Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                    ceiling=profile.default_ceiling(c))
        for c in profile.class_names()
    ]
    return KairosTwinAdapter(kairos, sage, principal.public_key_hex, [root], certs)


def test_robust_twin_contains_all_attacks(profile) -> None:
    sage = InMemorySagePort()
    twin = _empowered_twin(profile, sage)
    report = Basanos().integrity_suite(twin, profile)
    assert report.cases_run > 0
    assert report.passed, [f.model_dump() for f in report.findings]
    assert report.score == 1.0
    # all three suites ran
    assert {s.suite for s in report.suites} == {"memory-poisoning", "injection", "scope-evasion"}


def test_integrity_certificate_passes_for_robust_twin(profile) -> None:
    sage = InMemorySagePort()
    twin = _empowered_twin(profile, sage)
    basanos = Basanos()
    report = basanos.integrity_suite(twin, profile)
    cert = basanos.certify_integrity(report)
    assert cert.passed and cert.ceiling == "autonomous"


def test_weak_gate_is_caught(profile) -> None:
    # A broken twin that never contains anything (always "acts").
    class BrokenTwin:
        principal_id = "p"

        def poison(self, contents):
            pass

        def resolve(self, action, context):
            return "AUTONOMOUS_ACT"  # unsafe for every adversarial case

    report = Basanos().integrity_suite(BrokenTwin(), profile)
    assert not report.passed
    assert report.findings
    cert = Basanos().certify_integrity(report)
    assert not cert.passed and cert.ceiling == "draft"


def test_gating_caps_autonomy_without_integrity_cert(profile) -> None:
    basanos = Basanos()
    fidelity = [Certificate(action_class="post-status", agreement=1.0, calibration=1.0,
                            sample_size=10, ceiling="notify")]
    # gating off -> fidelity ceiling honored
    assert basanos.gated_ceiling("post-status", fidelity, None, require_integrity=False) == "notify"
    # gating on, no integrity cert -> capped at draft
    assert basanos.gated_ceiling("post-status", fidelity, None, require_integrity=True) == "draft"


def test_gate_downgrades_to_draft_when_integrity_required(profile) -> None:
    # With integrity gating ON and no integrity certificate, a post-status that
    # would otherwise NOTIFY_ACT is downgraded to DRAFT.
    settings = Settings(require_integrity_certification=True, style_enabled=False)
    sage = InMemorySagePort()
    for _ in range(5):
        sage.observe("seed", "x", "memory", "docs.read")  # noise, distinct principal
    twin = _empowered_twin(profile, sage, settings=settings)
    # seed grounding under the twin's principal
    for _ in range(5):
        sage.observe(twin.principal_id, "principal reports atlas status friday on track weekly", "memory", "docs.read")
    from eidolon.sage.port import Scope
    from eidolon.types import Action, Context

    action = Action(id="a", action_class="post-status",
                    description="post atlas status friday on track weekly",
                    scope=Scope(selectors={"project": ["atlas"]}), budget_cost={"posts_per_window": 1})
    ctx = Context(principal_id=twin.principal_id, query="post atlas status friday on track weekly")
    decision = twin._kairos.resolve(action, ctx, twin._chain, twin._certs)  # no integrity cert
    assert decision.level.value == "DRAFT"
