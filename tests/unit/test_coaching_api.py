"""Coaching over HTTP: resolve actions, then get a decoupled coaching report."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.common import crypto


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_STYLE_ENABLED", "false")
    import eidolon.api.app as app_module
    import eidolon.config as config

    config.get_settings.cache_clear()
    app_module._runtime = None
    return TestClient(app_module.app)


def test_coaching_report_reflects_ledger(client) -> None:
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    pid = principal.public_key_hex

    # A commit-action always escalates -> the ledger records an escalation.
    params = {
        "principal_id": pid, "issued_to": twin.public_key_hex,
        "scope": {"project": ["atlas"]},
        "permitted_classes": ["commit-action"], "escalation_required": ["commit-action"],
        "max_autonomy": "autonomous", "blast_radius_budget": {"scope_expansion": 0},
    }
    root = client.post("/delegations/mint",
                       json={"signing_key": principal.signing_key_hex, "params": params}).json()
    action = {"id": "a", "action_class": "commit-action", "description": "sign contract",
              "scope": {"selectors": {"project": ["atlas"]}}}
    ctx = {"principal_id": pid, "situation": "a binding contract"}
    r = client.post("/resolve", json={"action": action, "context": ctx, "chain": [root]})
    assert r.json()["level"] == "ESCALATE"

    # The principal aspires to escalate commit-action ~100% — which they do.
    aspiration = {
        "principal_id": pid,
        "values": ["Never bind the company without a human in the loop."],
        "targets": [{"action_class": "commit-action", "target_escalation_rate": 1.0}],
    }
    r = client.post("/coaching/report", json=aspiration)
    assert r.status_code == 200, r.text
    report = r.json()
    behavior = {b["action_class"]: b for b in report["behavior"]}
    assert behavior["commit-action"]["escalations"] >= 1
    # value reminder is surfaced
    assert any(n["topic"] == "value" for n in report["notes"])
