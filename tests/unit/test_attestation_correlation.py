"""Attestation correlation (known-issue #9) without disturbing existing hashes."""

from __future__ import annotations

import datetime as _dt

from eidolon.common.canonical import content_hash
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Attestation, ReplayFilter


def _rec(**kw) -> Attestation:
    base = {"action": "a", "action_class": "answer-status", "principal_id": "p",
            "timestamp": _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)}
    return Attestation(**{**base, **kw})


def test_uncorrelated_records_hash_exactly_as_before() -> None:
    legacy_payload = ('{"action":"a","action_class":"answer-status","autonomy_level":null,'
                      '"confidence":null,"delegation_chain":[],"ethos_version":null,'
                      '"evidence_refs":[],"judgment":null,"principal_id":"p","result":null,'
                      '"signature":null,"timestamp":"2026-01-01T00:00:00Z",'
                      '"would_have_escalated":false}')
    reparsed = Attestation.model_validate_json(legacy_payload)
    assert "correlation" not in reparsed.model_dump()
    assert content_hash(reparsed) == content_hash(_rec())


def test_correlation_is_hashed_when_present() -> None:
    assert content_hash(_rec(correlation={"session": "s1"})) != content_hash(_rec())


def test_replay_filters_by_correlation() -> None:
    sage = InMemorySagePort()
    sage.attest(_rec(correlation={"session": "s1", "task": "t1"}))
    sage.attest(_rec(action="b", correlation={"session": "s2"}))
    sage.attest(_rec(action="c"))
    hits = sage.replay(ReplayFilter(correlation={"session": "s1"}))
    assert [r.action for r in hits] == ["a"]
    assert len(sage.replay(ReplayFilter())) == 3


def test_gate_copies_correlation_to_the_ledger() -> None:
    from eidolon.common import crypto
    from eidolon.gateway.config import GatewayConfig, build_engine
    from eidolon.gateway.mapping import ToolPolicy
    from eidolon.sage.port import Scope

    key = crypto.generate_keypair()
    sage = InMemorySagePort()
    engine = build_engine(GatewayConfig(
        profile_id="general-continuity", principal_signing_key=key.signing_key_hex,
        scope={"project": ["ops"]},
        tool_policies=[ToolPolicy(tool="t", action_class="answer-status",
                                  scope=Scope(selectors={"project": ["ops"]}))]), sage=sage)
    engine.govern("t", {}, correlation={"run": "r-42"})
    engine.govern("t", {})
    assert len(sage.replay(ReplayFilter(correlation={"run": "r-42"}))) == 1
