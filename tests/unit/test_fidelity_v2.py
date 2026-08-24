"""Fidelity engine v2: grounding is more robust to surface variation, the
decision stays inspectable and deterministic, and certification works on a
labeled held-out set.
"""

from __future__ import annotations

import pytest

from eidolon.basanos import Basanos
from eidolon.basanos.certify import HeldoutDecision
from eidolon.ethos.facade import Ethos
from eidolon.ethos.judgment.grounding import HashingEmbedder, dice, normalize, relevance
from eidolon.ethos.types import Decision
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope
from eidolon.types import Action, Context


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


def test_normalization_collapses_surface_variation() -> None:
    assert normalize("get_balance") == ["get", "balance"]
    # plural / 3rd-person forms collapse to the same stem
    assert "balance" in normalize("balances")
    assert "summarize" in normalize("summarizes")
    assert "reserve" in normalize("reserves")


def test_relevance_grounds_where_exact_overlap_failed() -> None:
    # Old engine used exact token overlap → "get_balance" vs "reads balances" = 0.
    r = relevance("call tool get_balance", "the user reads balances and transactions")
    assert r > 0.15
    assert relevance("send_money", "note about the weather") == 0.0


def test_embedder_is_deterministic_and_offline() -> None:
    e = HashingEmbedder()
    assert e.embed("atlas status") == e.embed("atlas status")  # reproducible
    assert dice({"a", "b"}, {"b", "c"}) == pytest.approx(0.5)


def test_decision_is_deterministic_given_evidence(profile) -> None:
    # The embedder informs grounding, not the decision. With the SAME memories,
    # the decision/confidence are identical run to run (no black box).
    sage = InMemorySagePort()
    pid = "p"
    for _ in range(5):
        sage.observe(pid, "the user reads balances and transactions routinely", "memory", "docs.read")
    ethos = Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder())
    action = Action(id="a", action_class="answer-status", description="call tool get_balance",
                    scope=Scope(selectors={"project": ["bank"]}))
    ctx = Context(principal_id=pid, query="get balance")
    j1 = ethos.evaluate(action, ctx, None, profile)
    j2 = ethos.evaluate(action, ctx, None, profile)
    assert (j1.decision, j1.confidence) == (j2.decision, j2.confidence)
    assert j1.trace  # inspectable trace present


def test_grounding_improves_read_autonomy(profile) -> None:
    # With natural (non-verbatim) grounding, a routine read now proceeds where
    # brittle exact matching would have escalated.
    sage = InMemorySagePort()
    pid = "p"
    for _ in range(6):
        sage.observe(pid, "the user reads account balances and recent transactions every day",
                     "memory", "docs.read")
    ethos = Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder())
    action = Action(id="a", action_class="retrieve-context", description="get_balance and transactions",
                    scope=Scope(selectors={"project": ["bank"]}))
    ctx = Context(principal_id=pid, query="get balance and recent transactions")
    j = ethos.evaluate(action, ctx, None, profile)
    assert j.decision in (Decision.PROCEED, Decision.PROCEED_WITH_CARE)


def test_certify_fidelity_on_labeled_heldout(profile) -> None:
    # A twin that agrees with the principal on held-out decisions certifies;
    # agreement/calibration are reported against the rubric metric.
    sage = InMemorySagePort()
    pid = "p"
    for _ in range(6):
        sage.observe(pid, "the user answers project atlas status questions routinely", "memory", "docs.read")
    ethos = Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder())

    def twin_eval(action, ctx):
        return ethos.evaluate(action, ctx, None, profile)

    # Held-out: the principal DID proceed on well-grounded status questions.
    heldout = [
        HeldoutDecision(
            action=Action(id=f"h{i}", action_class="answer-status",
                          description="answer atlas status question", scope=Scope()),
            context=Context(principal_id=pid, query="atlas status question"),
            principal_decision="PROCEED",
        )
        for i in range(8)
    ]
    certs = Basanos().certify_fidelity(twin_eval, heldout, profile)
    answer = next(c for c in certs if c.action_class == "answer-status")
    assert answer.sample_size == 8
    assert answer.agreement >= 0.75  # decides like the principal
