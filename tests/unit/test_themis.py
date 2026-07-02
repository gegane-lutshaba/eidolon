"""THEMIS acceptance (PRD §6.3, §8):
- mint produces a signed, offline-verifiable credential;
- verify walks chain-to-root and fails closed on expired/revoked/broken chains;
- attenuate rejects any widening (property-tested);
- revocation < 1s to next verify; missed heartbeat auto-revokes.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from eidolon.common import crypto
from eidolon.common.errors import AttenuationError
from eidolon.sage.port import Scope
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window
from eidolon.types import Action


class FakeClock:
    def __init__(self, t: _dt.datetime) -> None:
        self.t = t

    def __call__(self) -> _dt.datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += _dt.timedelta(seconds=seconds)


@pytest.fixture
def principal():
    return crypto.generate_keypair()


@pytest.fixture
def twin():
    return crypto.generate_keypair()


def _root_params(principal_pub: str, twin_pub: str, **over) -> MintParams:
    base = dict(
        principal_id=principal_pub,
        issued_to=twin_pub,
        scope={"project": ["atlas", "borealis"], "channel": ["#eng"]},
        exclusions=["financial-commitment"],
        permitted_classes=["answer-status", "draft-comm", "post-status"],
        escalation_required=["commit-action"],
        window=Window(),
        blast_radius_budget={"posts_per_window": 5, "scope_expansion": 0},
        max_autonomy="notify",
        revocation=Revocation(dead_mans_switch=True),
        nonce="root-1",
    )
    base.update(over)
    return MintParams(**base)


def _action(cls="answer-status", scope=None, exclusions=None) -> Action:
    return Action(
        id="a",
        action_class=cls,
        description="d",
        scope=scope or Scope(selectors={"project": ["atlas"]}),
        touches_exclusions=exclusions or [],
    )


def test_mint_and_verify_offline(principal, twin) -> None:
    themis = Themis()
    root = themis.mint(principal.signing_key_hex, _root_params(principal.public_key_hex, twin.public_key_hex))
    res = themis.verify(_action(), [root])
    assert res.valid, res.reason
    assert res.effective and "answer-status" in res.effective.permitted_classes


def test_verify_rejects_tampered_signature(principal, twin) -> None:
    themis = Themis()
    root = themis.mint(principal.signing_key_hex, _root_params(principal.public_key_hex, twin.public_key_hex))
    tampered = root.model_copy(update={"signature": "00" * 64})
    assert not themis.verify(_action(), [tampered]).valid


def test_root_must_be_signed_by_principal(twin) -> None:
    themis = Themis()
    imposter = crypto.generate_keypair()
    # principal_id claims twin's key, but we sign with imposter -> reject
    with pytest.raises(AttenuationError):
        themis.mint(imposter.signing_key_hex, _root_params(twin.public_key_hex, twin.public_key_hex))


def test_attenuate_subset_ok_and_chain_verifies(principal, twin) -> None:
    themis = Themis()
    sub = crypto.generate_keypair()
    root = themis.mint(principal.signing_key_hex, _root_params(principal.public_key_hex, twin.public_key_hex))
    child_params = _root_params(
        principal.public_key_hex, sub.public_key_hex,
        scope={"project": ["atlas"]},  # narrower
        permitted_classes=["answer-status"],  # narrower
        exclusions=["financial-commitment", "legal-commitment"],  # more restrictive
        max_autonomy="draft",  # lower
        blast_radius_budget={"posts_per_window": 2, "scope_expansion": 0},
        nonce="child-1",
    )
    child = themis.attenuate(root, child_params, twin.signing_key_hex)
    res = themis.verify(_action(scope=Scope(selectors={"project": ["atlas"]})), [root, child])
    assert res.valid, res.reason
    assert res.effective.max_autonomy == "draft"


@pytest.mark.parametrize(
    "over,field",
    [
        ({"scope": {"project": ["atlas", "carina"]}}, "scope"),  # adds carina
        ({"permitted_classes": ["answer-status", "commit-action"]}, "classes"),
        ({"exclusions": []}, "exclusions"),  # removes a boundary
        ({"escalation_required": []}, "escalation"),  # removes escalation
        ({"max_autonomy": "autonomous"}, "autonomy"),  # widens
        ({"blast_radius_budget": {"posts_per_window": 99, "scope_expansion": 0}}, "budget"),
        ({"blast_radius_budget": {"posts_per_window": 5, "scope_expansion": 1}}, "scope_expansion"),
    ],
)
def test_attenuate_rejects_widening(principal, twin, over, field) -> None:
    themis = Themis()
    sub = crypto.generate_keypair()
    root = themis.mint(principal.signing_key_hex, _root_params(principal.public_key_hex, twin.public_key_hex))
    child_params = _root_params(principal.public_key_hex, sub.public_key_hex, nonce="c", **over)
    with pytest.raises(AttenuationError):
        themis.attenuate(root, child_params, twin.signing_key_hex)


def test_revocation_immediate(principal, twin) -> None:
    themis = Themis()
    root = themis.mint(principal.signing_key_hex, _root_params(principal.public_key_hex, twin.public_key_hex))
    assert themis.verify(_action(), [root]).valid
    themis.revoke(root.id)
    res = themis.verify(_action(), [root])  # very next call
    assert not res.valid and "revoked" in res.reason


def test_expired_window_fails_closed(principal, twin) -> None:
    clock = FakeClock(_dt.datetime(2026, 7, 2, 12, 0, tzinfo=_dt.UTC))
    themis = Themis(clock=clock)
    window = Window(not_after=_dt.datetime(2026, 7, 2, 13, 0, tzinfo=_dt.UTC))
    root = themis.mint(
        principal.signing_key_hex,
        _root_params(principal.public_key_hex, twin.public_key_hex, window=window),
    )
    assert themis.verify(_action(), [root]).valid
    clock.advance(7200)  # past not_after
    assert not themis.verify(_action(), [root]).valid


def test_dead_mans_switch_auto_revokes(principal, twin) -> None:
    clock = FakeClock(_dt.datetime(2026, 7, 2, 12, 0, tzinfo=_dt.UTC))
    themis = Themis(heartbeat_ttl_seconds=60, clock=clock)
    root = themis.mint(principal.signing_key_hex, _root_params(principal.public_key_hex, twin.public_key_hex))
    assert themis.verify(_action(), [root]).valid
    clock.advance(120)  # missed heartbeat window
    assert not themis.verify(_action(), [root]).valid
    themis.heartbeat(principal.public_key_hex)  # resets
    assert themis.verify(_action(), [root]).valid


def test_action_outside_scope_denied(principal, twin) -> None:
    themis = Themis()
    root = themis.mint(principal.signing_key_hex, _root_params(principal.public_key_hex, twin.public_key_hex))
    # carina not in grant
    res = themis.verify(_action(scope=Scope(selectors={"project": ["carina"]})), [root])
    assert not res.valid


def test_action_touching_exclusion_denied(principal, twin) -> None:
    themis = Themis()
    root = themis.mint(principal.signing_key_hex, _root_params(principal.public_key_hex, twin.public_key_hex))
    res = themis.verify(_action(cls="draft-comm", exclusions=["financial-commitment"]), [root])
    assert not res.valid
