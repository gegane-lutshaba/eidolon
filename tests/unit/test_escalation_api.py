"""Escalation approval loop over HTTP: resolve → inbox → approve → executed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.common import crypto


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_STYLE_ENABLED", "false")
    import eidolon.api.app as app_module

    app_module._runtime = None
    app_module._escalations = None  # fresh queue per test
    return TestClient(app_module.app)


def test_escalate_approve_execute_over_http(client) -> None:
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    pid = principal.public_key_hex

    params = {
        "principal_id": pid, "issued_to": twin.public_key_hex,
        "scope": {"project": ["atlas"]}, "permitted_classes": ["commit-action", "answer-status"],
        "escalation_required": ["commit-action"], "max_autonomy": "autonomous",
        "blast_radius_budget": {"scope_expansion": 0},
    }
    root = client.post("/delegations/mint",
                       json={"signing_key": principal.signing_key_hex, "params": params}).json()
    certs = [{"action_class": "commit-action", "agreement": 1.0, "calibration": 1.0,
              "sample_size": 10, "ceiling": "draft"}]
    action = {"id": "a", "action_class": "commit-action", "description": "sign the atlas contract",
              "scope": {"selectors": {"project": ["atlas"]}}}
    ctx = {"principal_id": pid, "situation": "contract"}

    # 1) resolve → escalate, enqueued to the inbox
    r = client.post("/resolve", json={"action": action, "context": ctx, "chain": [root], "certificates": certs})
    body = r.json()
    assert body["level"] == "ESCALATE"
    esc_id = body["escalation_id"]

    # 2) inbox shows it pending
    pending = client.get("/escalations", params={"principal_id": pid}).json()
    assert any(p["id"] == esc_id for p in pending)

    # 3) principal approves by signing → executes
    r = client.post(f"/escalations/{esc_id}/approve", json={"signing_key": principal.signing_key_hex})
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["level"] == "NOTIFY_ACT"

    # 4) no longer pending; ledger has both records
    assert client.get("/escalations", params={"principal_id": pid}).json() == []
    ledger = client.get("/replay", params={"principal_id": pid}).json()
    assert [x["autonomy_level"] for x in ledger] == ["ESCALATE", "NOTIFY_ACT"]


def test_approve_with_wrong_key_is_rejected(client) -> None:
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    pid = principal.public_key_hex
    params = {"principal_id": pid, "issued_to": twin.public_key_hex, "scope": {"project": ["atlas"]},
              "permitted_classes": ["commit-action"], "escalation_required": ["commit-action"],
              "max_autonomy": "autonomous", "blast_radius_budget": {"scope_expansion": 0}}
    root = client.post("/delegations/mint",
                       json={"signing_key": principal.signing_key_hex, "params": params}).json()
    action = {"id": "a", "action_class": "commit-action", "description": "sign", "scope": {"selectors": {"project": ["atlas"]}}}
    ctx = {"principal_id": pid}
    esc_id = client.post("/resolve", json={"action": action, "context": ctx, "chain": [root]}).json()["escalation_id"]
    imposter = crypto.generate_keypair()
    r = client.post(f"/escalations/{esc_id}/approve", json={"signing_key": imposter.signing_key_hex})
    assert r.status_code == 409  # not the principal's key
