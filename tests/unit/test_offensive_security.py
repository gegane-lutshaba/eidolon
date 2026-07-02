"""offensive-security profile acceptance (PRD §2.2, §2.3, §12).

Governance-only, lab/CTF-range, safe-by-construction:
- profile loads/validates and declares its safety flags;
- every impactful class (exploit/credential/lateral/persistence) ALWAYS escalates;
- an out-of-scope / boundary-touching target is denied or escalated;
- the profile is integrity-gated by construction — an acting level requires a
  passing integrity certificate even with the global flag OFF;
- benign recon within the authorized engagement is permitted (at its ceiling)
  once integrity-certified.
"""

from __future__ import annotations

import pytest

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.basanos.integrity.report import IntegrityCertificate
from eidolon.common import crypto
from eidolon.config import Settings
from eidolon.ethos.facade import Ethos
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger, DecisionLevel
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window
from eidolon.types import Action, Context

IMPACTFUL = ["exploit-execute", "credential-use", "lateral-movement", "persistence"]


@pytest.fixture
def profile():
    return ProfileLoader().load("offensive-security")


def test_profile_loads_and_declares_safety(profile) -> None:
    assert profile.id == "offensive-security"
    assert profile.requires_integrity_certification
    assert profile.authorization_required
    assert profile.lab_only
    # every impactful class always escalates and is capped at draft
    for cls in IMPACTFUL:
        assert profile.always_escalates(cls)
        assert profile.default_ceiling(cls) == "draft"


def _passing_integrity_cert(profile) -> IntegrityCertificate:
    return IntegrityCertificate(
        profile_id=profile.id, passed=True, score=1.0, cases_run=6, ceiling="autonomous"
    )


def _wire(profile, sage, *, settings=None):
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
            scope={"engagement": ["ctf-lab-01"], "target": ["10.0.0.5"]},
            exclusions=list(profile.mandate_schema.exclusion_types),
            permitted_classes=list(profile.class_names()),
            escalation_required=list(profile.mandate_schema.escalation_required),
            window=Window(),
            blast_radius_budget={"exploit_attempts_per_window": 3,
                                 "hosts_touched_per_window": 5, "scope_expansion": 0},
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
    return kairos, sage, principal, root, certs


def _seed(sage, pid, text="operator runs recon-active scans on authorized engagement targets routinely"):
    for _ in range(5):
        sage.observe(pid, text, "memory", "engagement.notes")


def test_impactful_classes_always_escalate(profile) -> None:
    sage = InMemorySagePort()
    kairos, sage, principal, root, certs = _wire(profile, sage)
    pid = principal.public_key_hex
    _seed(sage, pid)
    cert = _passing_integrity_cert(profile)
    for cls in IMPACTFUL:
        action = Action(id=cls, action_class=cls, description=f"{cls} on host",
                        scope=Scope(selectors={"engagement": ["ctf-lab-01"], "target": ["10.0.0.5"]}))
        ctx = Context(principal_id=pid, situation=f"{cls} step")
        d = kairos.resolve(action, ctx, [root], certs, cert)
        assert d.level == DecisionLevel.ESCALATE, cls


def test_out_of_scope_target_denied(profile) -> None:
    sage = InMemorySagePort()
    kairos, sage, principal, root, certs = _wire(profile, sage)
    pid = principal.public_key_hex
    _seed(sage, pid)
    cert = _passing_integrity_cert(profile)
    # recon against a boundary category (out-of-scope target) must be denied
    action = Action(id="r", action_class="recon-active", description="scan external asset",
                    scope=Scope(selectors={"engagement": ["ctf-lab-01"], "target": ["10.0.0.5"]}),
                    touches_exclusions=["out-of-scope-target"])
    ctx = Context(principal_id=pid, situation="scan")
    d = kairos.resolve(action, ctx, [root], certs, cert)
    assert d.level == DecisionLevel.DENY


def test_target_outside_grant_denied(profile) -> None:
    sage = InMemorySagePort()
    kairos, sage, principal, root, certs = _wire(profile, sage)
    pid = principal.public_key_hex
    _seed(sage, pid)
    cert = _passing_integrity_cert(profile)
    # a target not present in the delegation scope is denied by authority
    action = Action(id="r", action_class="recon-active", description="scan host",
                    scope=Scope(selectors={"engagement": ["ctf-lab-01"], "target": ["8.8.8.8"]}))
    ctx = Context(principal_id=pid, situation="scan")
    d = kairos.resolve(action, ctx, [root], certs, cert)
    assert d.level == DecisionLevel.DENY


def test_integrity_gated_by_construction(profile) -> None:
    # Global integrity flag OFF, but the profile requires it -> recon-active
    # (ceiling notify) is downgraded to DRAFT without an integrity certificate.
    sage = InMemorySagePort()
    settings = Settings(require_integrity_certification=False, style_enabled=False)
    kairos, sage, principal, root, certs = _wire(profile, sage, settings=settings)
    pid = principal.public_key_hex
    _seed(sage, pid)
    action = Action(id="r", action_class="recon-active",
                    description="operator runs recon-active scans on authorized engagement targets",
                    scope=Scope(selectors={"engagement": ["ctf-lab-01"], "target": ["10.0.0.5"]}),
                    budget_cost={"hosts_touched_per_window": 1})
    ctx = Context(principal_id=pid, query="operator runs recon-active scans on authorized engagement targets")
    # no integrity certificate supplied
    d_no_cert = kairos.resolve(action, ctx, [root], certs, None)
    assert d_no_cert.level == DecisionLevel.DRAFT
    # with a passing integrity certificate, recon may act at its ceiling (notify)
    d_cert = kairos.resolve(action, ctx, [root], certs, _passing_integrity_cert(profile))
    assert d_cert.level == DecisionLevel.NOTIFY_ACT
