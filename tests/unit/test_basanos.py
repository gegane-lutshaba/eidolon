"""BASANOS fidelity certification acceptance (PRD §6.6):
- uncertified class returns ceiling observe;
- ceiling never exceeds what the certificate supports;
- integrity suite is a v2 stub (NotImplementedError).
"""

from __future__ import annotations

import pytest

from eidolon.basanos import Basanos
from eidolon.basanos.certify import HeldoutDecision
from eidolon.ethos.types import Decision, Judgment
from eidolon.profile import ProfileLoader
from eidolon.types import Action, Context


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


def test_uncertified_class_defaults_to_observe() -> None:
    assert Basanos().autonomy_ceiling("post-status", []) == "observe"


def test_integrity_suite_is_v2_stub(profile) -> None:
    with pytest.raises(NotImplementedError):
        Basanos().integrity_suite(twin=object(), profile=profile)


def _heldout(cls: str, decision: str, escalated: bool = False) -> HeldoutDecision:
    return HeldoutDecision(
        action=Action(id="h", action_class=cls, description="d"),
        context=Context(principal_id="p"),
        principal_decision=decision,
        principal_escalated=escalated,
    )


def test_perfect_agreement_certifies_up_to_default_ceiling(profile) -> None:
    # A twin that always agrees with the principal earns the class's default
    # ceiling — never more.
    def twin_eval(action: Action, ctx: Context) -> Judgment:
        return Judgment(decision=Decision.PROCEED, confidence=0.95, rationale="", action_class=action.action_class)

    heldout = [_heldout("answer-status", "PROCEED") for _ in range(10)]
    certs = Basanos().certify_fidelity(twin_eval, heldout, profile)
    answer = next(c for c in certs if c.action_class == "answer-status")
    assert answer.agreement == 1.0
    assert answer.ceiling == profile.default_ceiling("answer-status")  # 'autonomous'


def test_disagreement_caps_at_observe(profile) -> None:
    # A twin that always says PROCEED while the principal always STOPs fails.
    def twin_eval(action: Action, ctx: Context) -> Judgment:
        return Judgment(decision=Decision.PROCEED, confidence=0.9, rationale="", action_class=action.action_class)

    heldout = [_heldout("post-status", "STOP", escalated=True) for _ in range(10)]
    certs = Basanos().certify_fidelity(twin_eval, heldout, profile)
    post = next(c for c in certs if c.action_class == "post-status")
    assert post.agreement == 0.0
    assert post.ceiling == "observe"


def test_no_samples_yields_observe(profile) -> None:
    def twin_eval(action: Action, ctx: Context) -> Judgment:
        return Judgment(decision=Decision.PROCEED, confidence=0.9, rationale="")

    certs = Basanos().certify_fidelity(twin_eval, [], profile)
    assert all(c.ceiling == "observe" and c.sample_size == 0 for c in certs)
