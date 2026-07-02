"""ETHOS judgment-policy behavior (PRD §6.2)."""

from __future__ import annotations

import pytest

from eidolon.ethos.facade import Ethos
from eidolon.ethos.types import Decision
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.types import Action, Context


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


@pytest.fixture
def ethos():
    return Ethos(InMemorySagePort(), style=None)


def test_exclusion_touch_stops(ethos, profile) -> None:
    action = Action(
        id="a1",
        action_class="draft-comm",
        description="approve a $50k vendor payment",
        touches_exclusions=["financial-commitment"],
    )
    ctx = Context(principal_id="p", query="vendor payment")
    j = ethos.evaluate(action, ctx, None, profile)
    assert j.decision == Decision.STOP
    assert j.confidence >= 0.9  # confident the principal would NOT act


def test_thin_evidence_stops_low_confidence(ethos, profile) -> None:
    action = Action(id="a2", action_class="answer-status", description="obscure unknown topic")
    ctx = Context(principal_id="p", query="obscure unknown topic")
    j = ethos.evaluate(action, ctx, None, profile)  # no memories seeded
    assert j.decision == Decision.STOP
    assert j.confidence < 0.7


def test_strong_evidence_proceeds(profile) -> None:
    sage = InMemorySagePort()
    principal = "p"
    for _ in range(4):
        sage.observe(principal, "principal answers atlas status weekly on track friday", "memory", "docs.read")
    ethos = Ethos(sage, style=None)
    action = Action(id="a3", action_class="answer-status", description="atlas status weekly friday")
    ctx = Context(principal_id=principal, query="atlas status weekly friday on track")
    j = ethos.evaluate(action, ctx, None, profile)
    assert j.decision in (Decision.PROCEED, Decision.PROCEED_WITH_CARE)
    assert j.confidence > 0.5


def test_threshold_from_profile(ethos, profile) -> None:
    # decision points in the rubric are held to at least the calibration target
    assert ethos.confidence_threshold("answer-status", profile) >= profile.fidelity_rubric.calibration_target
    # non-decision-point classes use the default
    assert ethos.confidence_threshold("commit-action", profile) == 0.7
