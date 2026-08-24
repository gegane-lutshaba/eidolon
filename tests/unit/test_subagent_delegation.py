"""Sub-agent delegation e2e (#8): a twin attenuates to a sub-agent; the chain
root→twin→sub-agent is bounded to a cryptographic subset and cannot widen.
"""

from __future__ import annotations

import pytest

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.ethos.facade import Ethos
from eidolon.ethos.judgment.grounding import HashingEmbedder
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger, DecisionLevel
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window
from eidolon.types import Action, Context


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


def test_subagent_chain_is_bounded_to_a_subset(profile) -> None:
    sage = InMemorySagePort()
    ada, twin, sub = crypto.generate_keypair(), crypto.generate_keypair(), crypto.generate_keypair()
    pid = ada.public_key_hex
    for _ in range(6):
        sage.observe(pid, "the principal answers atlas and borealis status routinely", "memory", "docs.read")
    themis = Themis()
    kairos = Kairos(themis=themis, ethos=Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder()),
                    basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile, budget=BudgetLedger())
    certs = [Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                         ceiling=profile.default_ceiling(c)) for c in profile.class_names()]

    root = themis.mint(ada.signing_key_hex, MintParams(
        principal_id=pid, issued_to=twin.public_key_hex,
        scope={"project": ["atlas", "borealis"]}, exclusions=list(profile.mandate_schema.exclusion_types),
        permitted_classes=["answer-status", "draft-comm"], escalation_required=["commit-action"],
        window=Window(), blast_radius_budget={"scope_expansion": 0}, max_autonomy="autonomous",
        revocation=Revocation(), nonce="root"))
    child = themis.attenuate(root, MintParams(
        principal_id=pid, issued_to=sub.public_key_hex, scope={"project": ["atlas"]},
        exclusions=list(profile.mandate_schema.exclusion_types), permitted_classes=["answer-status"],
        escalation_required=["commit-action"], window=Window(),
        blast_radius_budget={"scope_expansion": 0}, max_autonomy="notify", nonce="child"),
        twin.signing_key_hex)
    chain = [root, child]

    def resolve(cls, project):
        a = Action(id=cls, action_class=cls, description=f"{cls} on {project}",
                   scope=Scope(selectors={"project": [project]}))
        return kairos.resolve(a, Context(principal_id=pid, query=f"{cls} {project} status"), chain, certs)

    assert resolve("answer-status", "atlas").level in (DecisionLevel.AUTONOMOUS_ACT, DecisionLevel.NOTIFY_ACT)
    assert resolve("draft-comm", "atlas").level == DecisionLevel.DENY       # class not sub-delegated
    assert resolve("answer-status", "borealis").level == DecisionLevel.DENY  # scope not sub-delegated


def test_widening_attenuation_to_subagent_is_rejected(profile) -> None:
    from eidolon.common.errors import AttenuationError

    themis = Themis()
    ada, twin, sub = crypto.generate_keypair(), crypto.generate_keypair(), crypto.generate_keypair()
    pid = ada.public_key_hex
    root = themis.mint(ada.signing_key_hex, MintParams(
        principal_id=pid, issued_to=twin.public_key_hex, scope={"project": ["atlas"]},
        exclusions=["financial-commitment"], permitted_classes=["answer-status"],
        escalation_required=["commit-action"], window=Window(),
        blast_radius_budget={"scope_expansion": 0}, max_autonomy="notify", revocation=Revocation(), nonce="root"))
    with pytest.raises(AttenuationError):
        themis.attenuate(root, MintParams(
            principal_id=pid, issued_to=sub.public_key_hex, scope={"project": ["atlas"]},
            exclusions=["financial-commitment"], permitted_classes=["answer-status", "commit-action"],  # widen
            escalation_required=["commit-action"], window=Window(),
            blast_radius_budget={"scope_expansion": 0}, max_autonomy="notify", nonce="bad"),
            twin.signing_key_hex)
