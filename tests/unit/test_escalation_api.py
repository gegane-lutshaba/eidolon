"""Escalation approval loop over HTTP: resolve → inbox → approve → executed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.basanos import Certificate
from eidolon.common import crypto


def _issued_cert(principal_id: str, action_class: str, ceiling: str) -> dict:
    """A certificate as this server issues it (signed, principal-bound)."""
    import eidolon.api.app as app_module

    cert = Certificate(action_class=action_class, agreement=1.0, calibration=1.0,
                       sample_size=10, ceiling=ceiling)
    return app_module.runtime().issuer.sign(cert, principal_id).model_dump(mode="json")


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
    certs = [_issued_cert(pid, "commit-action", "draft")]
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


def _mint(client, principal, classes):
    params = {"principal_id": principal.public_key_hex,
              "issued_to": crypto.generate_keypair().public_key_hex,
              "scope": {"project": ["atlas"]}, "permitted_classes": classes,
              "escalation_required": [], "max_autonomy": "autonomous",
              "blast_radius_budget": {"scope_expansion": 0}}
    return client.post("/delegations/mint",
                       json={"signing_key": principal.signing_key_hex, "params": params}).json()


def test_forged_certificate_cannot_lift_the_ceiling(client) -> None:
    """Known-issue #1: a caller asserting agreement=1.0 gets nothing for it."""
    principal = crypto.generate_keypair()
    pid = principal.public_key_hex
    root = _mint(client, principal, ["post-status"])
    action = {"id": "a", "action_class": "post-status", "description": "post atlas status",
              "scope": {"selectors": {"project": ["atlas"]}}}
    forged = {"action_class": "post-status", "agreement": 1.0, "calibration": 1.0,
              "sample_size": 99, "ceiling": "notify"}
    body = client.post("/resolve", json={"action": action, "context": {"principal_id": pid},
                                         "chain": [root], "certificates": [forged]}).json()
    assert body["certificates_rejected"] == ["post-status"]
    assert body["level"] not in ("NOTIFY_ACT", "AUTONOMOUS_ACT")


def test_issued_certificate_is_bound_to_its_principal(client) -> None:
    alice, mallory = crypto.generate_keypair(), crypto.generate_keypair()
    stolen = _issued_cert(alice.public_key_hex, "post-status", "notify")
    root = _mint(client, mallory, ["post-status"])
    action = {"id": "a", "action_class": "post-status", "description": "post status",
              "scope": {"selectors": {"project": ["atlas"]}}}
    body = client.post("/resolve", json={
        "action": action, "context": {"principal_id": mallory.public_key_hex},
        "chain": [root], "certificates": [stolen]}).json()
    assert body["certificates_rejected"] == ["post-status"]


def test_tampered_issued_certificate_is_rejected(client) -> None:
    principal = crypto.generate_keypair()
    cert = _issued_cert(principal.public_key_hex, "post-status", "draft")
    cert["ceiling"] = "autonomous"  # lift it after issuance
    root = _mint(client, principal, ["post-status"])
    action = {"id": "a", "action_class": "post-status", "description": "post status",
              "scope": {"selectors": {"project": ["atlas"]}}}
    body = client.post("/resolve", json={
        "action": action, "context": {"principal_id": principal.public_key_hex},
        "chain": [root], "certificates": [cert]}).json()
    assert body["certificates_rejected"] == ["post-status"]
