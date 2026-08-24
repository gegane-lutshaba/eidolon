"""Escalation approval workflow (#7): escalate → approve (signed) → execute,
attested — and an approval can never grant authority the credential lacks.
"""

from __future__ import annotations

import pytest

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.escalation import (
    EscalationQueue,
    action_digest,
    make_approval,
    verify_approval,
)
from eidolon.ethos.facade import Ethos
from eidolon.ethos.judgment.grounding import HashingEmbedder
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger, DecisionLevel
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import ReplayFilter, Scope
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window
from eidolon.types import Action, Context


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


@pytest.fixture
def setup(profile):
    sage = InMemorySagePort()
    principal, twin = crypto.generate_keypair(), crypto.generate_keypair()
    pid = principal.public_key_hex
    themis = Themis()
    kairos = Kairos(themis=themis, ethos=Ethos(sage, style=None, profile=profile, embedder=HashingEmbedder()),
                    basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile, budget=BudgetLedger())
    root = themis.mint(principal.signing_key_hex, MintParams(
        principal_id=pid, issued_to=twin.public_key_hex, scope={"project": ["atlas"]},
        exclusions=list(profile.mandate_schema.exclusion_types), permitted_classes=list(profile.class_names()),
        escalation_required=["commit-action"], window=Window(),
        blast_radius_budget={"scope_expansion": 0}, max_autonomy="autonomous",
        revocation=Revocation(), nonce="r"))
    certs = [Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                         ceiling=profile.default_ceiling(c)) for c in profile.class_names()]
    return sage, kairos, themis, principal, root, certs


def _commit(scope_val="atlas"):
    return Action(id="a", action_class="commit-action", description="sign the atlas vendor contract",
                  scope=Scope(selectors={"project": [scope_val]}))


def test_escalate_enqueue_approve_execute(setup) -> None:
    sage, kairos, _themis, principal, root, certs = setup
    pid = principal.public_key_hex
    action, ctx = _commit(), Context(principal_id=pid, situation="contract")

    d = kairos.resolve(action, ctx, [root], certs)
    assert d.level == DecisionLevel.ESCALATE

    q = EscalationQueue()
    req = q.enqueue(d, action, ctx)
    assert [r.id for r in q.list_pending(pid)] == [req.id]

    approval = q.approve(req.id, principal.signing_key_hex)
    d2 = kairos.resolve_with_approval(action, ctx, [root], approval, certs)
    assert d2.level == DecisionLevel.NOTIFY_ACT  # executed under approval
    assert q.list_pending(pid) == []  # no longer pending

    # both the escalation and the approved execution are attested
    rows = sage.replay(ReplayFilter(principal_id=pid))
    assert [r.autonomy_level for r in rows] == ["ESCALATE", "NOTIFY_ACT"]


def test_expired_approval_is_rejected(setup) -> None:
    sage, kairos, _themis, principal, root, certs = setup
    pid = principal.public_key_hex
    action, ctx = _commit(), Context(principal_id=pid)
    approval = make_approval(action, pid, principal.signing_key_hex, ttl_seconds=-1)  # already expired
    d = kairos.resolve_with_approval(action, ctx, [root], approval, certs)
    assert d.level == DecisionLevel.DENY


def test_wrong_signer_rejected_at_creation(setup) -> None:
    _sage, _kairos, _themis, principal, _root, _certs = setup
    imposter = crypto.generate_keypair()
    with pytest.raises(ValueError):
        make_approval(_commit(), principal.public_key_hex, imposter.signing_key_hex)


def test_approval_for_different_action_does_not_match(setup) -> None:
    _sage, kairos, _themis, principal, root, certs = setup
    pid = principal.public_key_hex
    approval = make_approval(_commit(), pid, principal.signing_key_hex)
    other = Action(id="b", action_class="commit-action", description="wire $1M to a stranger",
                   scope=Scope(selectors={"project": ["atlas"]}))
    assert not verify_approval(approval, other, pid)
    assert kairos.resolve_with_approval(other, Context(principal_id=pid), [root], approval, certs).level == DecisionLevel.DENY


def test_approval_cannot_override_revoked_authority(setup) -> None:
    _sage, kairos, themis, principal, root, certs = setup
    pid = principal.public_key_hex
    action, ctx = _commit(), Context(principal_id=pid)
    approval = make_approval(action, pid, principal.signing_key_hex)
    themis.revoke(root.id)  # authority pulled
    d = kairos.resolve_with_approval(action, ctx, [root], approval, certs)
    assert d.level == DecisionLevel.DENY  # approval releases an escalation, not authority


def test_approval_cannot_extend_scope(setup) -> None:
    _sage, kairos, _themis, principal, root, certs = setup
    pid = principal.public_key_hex
    # approve an out-of-scope action; THEMIS still denies (scope isn't granted)
    action = _commit(scope_val="carina")  # not in the grant
    ctx = Context(principal_id=pid)
    approval = make_approval(action, pid, principal.signing_key_hex)
    assert kairos.resolve_with_approval(action, ctx, [root], approval, certs).level == DecisionLevel.DENY


def test_digest_is_stable_and_action_specific() -> None:
    a1 = _commit()
    a2 = _commit()
    assert action_digest(a1, "p") == action_digest(a2, "p")  # same semantics
    a3 = Action(id="a", action_class="commit-action", description="different", scope=a1.scope)
    assert action_digest(a3, "p") != action_digest(a1, "p")
