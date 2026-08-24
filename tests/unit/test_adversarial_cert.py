"""Automated adversarial certification (#6): the twin must contain FRESH,
generated attacks over multiple rounds to earn its integrity certificate.
"""

from __future__ import annotations

import pytest

from eidolon.basanos import Basanos, KairosTwinAdapter
from eidolon.basanos.certify import Certificate
from eidolon.basanos.integrity import ProceduralAttacker
from eidolon.basanos.integrity.attacker import LLMAttacker
from eidolon.common import crypto
from eidolon.config import Settings
from eidolon.ethos.facade import Ethos
from eidolon.ethos.judgment.grounding import HashingEmbedder
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


def _robust_twin(profile):
    sage = InMemorySagePort()
    principal, twin = crypto.generate_keypair(), crypto.generate_keypair()
    pid = principal.public_key_hex
    for _ in range(5):
        sage.observe(pid, "the principal answers atlas status routinely", "memory", "docs.read")
    themis = Themis()
    kairos = Kairos(themis=themis, ethos=Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder()),
                    basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile, budget=BudgetLedger())
    root = themis.mint(principal.signing_key_hex, MintParams(
        principal_id=pid, issued_to=twin.public_key_hex, scope={"project": ["atlas"], "channel": ["#eng"]},
        exclusions=list(profile.mandate_schema.exclusion_types), permitted_classes=list(profile.class_names()),
        escalation_required=["commit-action"], window=Window(),
        blast_radius_budget={"posts_per_window": 5, "scope_expansion": 0}, max_autonomy="autonomous",
        revocation=Revocation(), nonce="r"))
    certs = [Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                         ceiling=profile.default_ceiling(c)) for c in profile.class_names()]
    return KairosTwinAdapter(kairos, sage, pid, [root], certs)


class _BrokenTwin:
    principal_id = "p"

    def poison(self, contents):
        pass

    def resolve(self, action, context):
        return "AUTONOMOUS_ACT"  # never contains anything


def test_procedural_attacker_generates_diverse_cases(profile) -> None:
    cases = ProceduralAttacker().generate(profile, "p", 30, seed=1)
    assert len(cases) == 30
    suites = {c.suite for c in cases}
    assert len(suites) >= 2  # multiple vectors
    assert all(c.safe_levels for c in cases)  # every case expects containment


def test_fresh_attacks_differ_per_round(profile) -> None:
    a = {c.name for c in ProceduralAttacker().generate(profile, "p", 20, seed=1)}
    b = {c.name for c in ProceduralAttacker().generate(profile, "p", 20, seed=1001)}
    assert a != b  # rounds produce fresh cases


def test_robust_twin_certifies_against_generated_attacks(profile) -> None:
    cert, report = Basanos().certify_integrity_adversarial(_robust_twin(profile), profile, rounds=3, per_round=24)
    assert report.cases_run >= 70
    assert report.passed and cert.passed and cert.ceiling == "autonomous"


def test_broken_twin_fails_adversarial_certification(profile) -> None:
    cert, report = Basanos().certify_integrity_adversarial(_BrokenTwin(), profile, rounds=2, per_round=20)
    assert not cert.passed and cert.ceiling == "draft"
    assert report.findings  # the attacker found uncontained cases


def test_llm_attacker_falls_back_without_key(profile) -> None:
    # No API key → falls back to procedural generation (certification never
    # depends on model availability).
    attacker = LLMAttacker(Settings(anthropic_api_key=None))
    cases = attacker.generate(profile, "p", 10, seed=0)
    assert len(cases) == 10


def test_demo_runs(monkeypatch) -> None:
    # Force the offline procedural attacker so the smoke test makes no API calls.
    monkeypatch.setenv("EIDOLON_ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("sys.argv", ["adversarial_cert"])
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[2] / "examples/adversarial_cert.py"
    spec = importlib.util.spec_from_file_location("adversarial_cert", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0
