"""GovernanceEngine approval path (known-issue #16): an escalated call can be
re-resolved under the principal's signed approval without reimplementing the
engine's action construction — and an approval can't launder a new exclusion.
"""

from __future__ import annotations

from eidolon.common import crypto
from eidolon.escalation.types import make_approval
from eidolon.gateway.config import GatewayConfig, build_engine
from eidolon.gateway.mapping import ToolPolicy
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope

SCOPE = Scope(selectors={"project": ["ops"]})
IBAN = "DE89370400440532013000"


def _engine(key):
    cfg = GatewayConfig(
        profile_id="general-continuity",
        principal_signing_key=key.signing_key_hex,
        scope={"project": ["ops"]},
        seed_memories=["the operator will get customer records and send contracts routinely"] * 6,
        tool_policies=[
            ToolPolicy(tool="get_customer", action_class="retrieve-context", scope=SCOPE,
                       sensitive=True),
            ToolPolicy(tool="send_contract", action_class="commit-action", scope=SCOPE,
                       egress=True),
        ],
    )
    return build_engine(cfg, sage=InMemorySagePort())


def test_escalated_call_runs_under_a_signed_approval() -> None:
    key = crypto.generate_keypair()
    engine = _engine(key)
    args = {"to": "legal@acme.example", "body": "please countersign"}
    ran = []

    first = engine.govern("send_contract", args, lambda t, a: ran.append(t))
    assert first.level == "ESCALATE" and not ran

    approval = make_approval(engine.action_for("send_contract", args),
                             key.public_key_hex, key.signing_key_hex)
    r = engine.govern_with_approval("send_contract", args, approval, lambda t, a: ran.append(t) or "sent")
    assert r.allowed and r.attestation_hash
    assert ran == ["send_contract"]


def test_approval_is_bound_to_the_exact_arguments() -> None:
    key = crypto.generate_keypair()
    engine = _engine(key)
    approved = {"to": "legal@acme.example", "body": "countersign"}
    approval = make_approval(engine.action_for("send_contract", approved),
                             key.public_key_hex, key.signing_key_hex)
    other = {"to": "attacker@evil.example", "body": "countersign"}
    r = engine.decide_with_approval("send_contract", other, approval)
    assert r.level == "DENY" and not r.allowed


def test_approval_from_another_key_is_refused() -> None:
    key, mallory = crypto.generate_keypair(), crypto.generate_keypair()
    engine = _engine(key)
    args = {"to": "legal@acme.example"}
    forged = make_approval(engine.action_for("send_contract", args),
                           mallory.public_key_hex, mallory.signing_key_hex)
    assert not engine.decide_with_approval("send_contract", args, forged).allowed


def test_approval_cannot_launder_a_taint_exclusion() -> None:
    """Approve a call, THEN the agent reads a secret the arguments carry: the
    rebuilt action now touches data-exfiltration, so the old approval no longer
    matches and the call is denied — never forwarded."""
    key = crypto.generate_keypair()
    engine = _engine(key)
    args = {"to": "partner@x.example", "body": f"account {IBAN}"}
    approval = make_approval(engine.action_for("send_contract", args),
                             key.public_key_hex, key.signing_key_hex)

    engine.govern("get_customer", {"id": "acme"}, lambda t, a: f"customer acme iban {IBAN}")
    assert "data-exfiltration" in engine.action_for("send_contract", args).touches_exclusions

    ran = []
    r = engine.govern_with_approval("send_contract", args, approval, lambda t, a: ran.append(t))
    assert r.level == "DENY" and not ran
