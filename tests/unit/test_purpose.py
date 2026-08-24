"""Purpose-binding / privacy limitation (#10): data collected for one purpose
cannot flow into a tool serving an incompatible purpose (ToolPrivacyBench-style).
"""

from __future__ import annotations

import pytest

from eidolon.common import crypto
from eidolon.gateway.config import GatewayConfig, build_engine
from eidolon.gateway.mapping import ToolPolicy
from eidolon.gateway.purpose import PURPOSE_LIMITATION, PurposeTracker
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope

PHI = "DE89370400440532013000"  # a record identifier extracted from a read


def test_tracker_flags_cross_purpose_flow() -> None:
    t = PurposeTracker()
    t.observe(f"record {PHI} stable", "treatment")
    # same purpose → ok; different purpose → violation
    assert t.purpose_violations({"body": PHI}, "treatment") == []
    assert t.purpose_violations({"body": PHI}, "marketing") == [PURPOSE_LIMITATION]
    assert t.purpose_violations({"body": "nothing"}, "marketing") == []


def test_compatibility_map_allows_declared_secondary_use() -> None:
    # A compatibility function can permit declared secondary uses.
    compat = {("treatment", "billing")}
    t = PurposeTracker(compatible=lambda c, u: c == u or (c, u) in compat)
    t.observe(f"record {PHI}", "treatment")
    assert t.purpose_violations({"x": PHI}, "billing") == []       # allowed secondary use
    assert t.purpose_violations({"x": PHI}, "marketing") == [PURPOSE_LIMITATION]


@pytest.fixture
def engine():
    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="general-continuity", principal_signing_key=key.signing_key_hex,
        scope={"project": ["clinic"]},
        seed_memories=["the user reads medical records and sends care updates and marketing routinely"] * 6,
        tool_policies=[
            ToolPolicy(tool="get_medical_records", action_class="retrieve-context", purpose="treatment",
                       scope=Scope(selectors={"project": ["clinic"]})),
            ToolPolicy(tool="send_care_update", action_class="draft-comm", purpose="treatment",
                       scope=Scope(selectors={"project": ["clinic"]})),
            ToolPolicy(tool="send_marketing", action_class="draft-comm", purpose="marketing",
                       scope=Scope(selectors={"project": ["clinic"]})),
        ],
    )
    return build_engine(cfg, sage=InMemorySagePort())


def _downstream(tool, args):
    return f"patient record id {PHI} diagnosis stable" if tool == "get_medical_records" else "ok"


def test_cross_purpose_use_is_denied(engine) -> None:
    engine.govern("get_medical_records", {"patient": "ada"}, _downstream)  # collected for treatment
    # treatment → allowed (drafted); marketing → denied
    assert engine.govern("send_care_update", {"body": PHI}, _downstream).level == "DRAFT"
    assert engine.govern("send_marketing", {"body": PHI}, _downstream).level == "DENY"


def test_no_phi_no_violation(engine) -> None:
    engine.govern("get_medical_records", {"patient": "ada"}, _downstream)
    # marketing that carries no collected data is handled normally, not exfil-denied
    assert engine.govern("send_marketing", {"body": "generic promo"}, _downstream).level != "DENY"
