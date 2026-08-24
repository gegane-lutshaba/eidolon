"""THEMIS ⇄ biscuit standards interop (Tier 2, #4).

Runs only if the optional `biscuit` extra is installed (`uv sync --extra biscuit`).
"""

from __future__ import annotations

import importlib.util

import pytest

from eidolon.common import crypto
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window

_HAS_BISCUIT = importlib.util.find_spec("biscuit_auth") is not None
pytestmark = pytest.mark.skipif(not _HAS_BISCUIT, reason="biscuit not installed (uv sync --extra biscuit)")


def _delegation():
    principal, twin = crypto.generate_keypair(), crypto.generate_keypair()
    root = Themis().mint(principal.signing_key_hex, MintParams(
        principal_id=principal.public_key_hex, issued_to=twin.public_key_hex,
        scope={"project": ["atlas"]}, exclusions=["financial-commitment"],
        permitted_classes=["answer-status", "draft-comm", "post-status"],
        escalation_required=["commit-action"], window=Window(),
        blast_radius_budget={"scope_expansion": 0}, max_autonomy="notify",
        revocation=Revocation(), nonce="r"))
    return root


def test_export_and_authorize() -> None:
    from eidolon.themis.interop import authorize_biscuit, delegation_to_biscuit

    token, pub = delegation_to_biscuit(_delegation())
    assert token and len(pub) == 64  # base64 token + hex pubkey
    assert authorize_biscuit(token, pub, "answer-status")[0] is True
    assert authorize_biscuit(token, pub, "commit-action")[0] is False  # not permitted
    # a permitted class that touches a hard exclusion is denied
    assert authorize_biscuit(token, pub, "draft-comm", touches_exclusions=["financial-commitment"])[0] is False


def test_offline_attenuation_only_narrows() -> None:
    from eidolon.themis.interop import attenuate_biscuit, authorize_biscuit, delegation_to_biscuit

    token, pub = delegation_to_biscuit(_delegation())
    # draft-comm is permitted in the original token
    assert authorize_biscuit(token, pub, "draft-comm")[0] is True
    # attenuate to answer-status only — WITHOUT the root key (offline)
    narrowed = attenuate_biscuit(token, pub, ["answer-status"])
    assert authorize_biscuit(narrowed, pub, "answer-status")[0] is True
    assert authorize_biscuit(narrowed, pub, "draft-comm")[0] is False  # narrowed away


def test_tampered_token_fails_verification() -> None:
    import biscuit_auth as ba

    from eidolon.themis.interop import delegation_to_biscuit

    token, _pub = delegation_to_biscuit(_delegation())
    other = ba.KeyPair()  # verifying with the wrong public key must fail
    with pytest.raises(ba.BiscuitValidationError):
        ba.Biscuit.from_base64(token, other.public_key)
