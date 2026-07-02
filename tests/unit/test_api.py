"""End-to-end API smoke over the in-memory SAGE backend.

Exercises the full gate through HTTP: mint -> attenuate -> resolve -> replay.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.common import crypto


@pytest.fixture
def client(monkeypatch):
    # Force the in-memory SAGE backend and a fresh runtime for the app.
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_STYLE_ENABLED", "false")
    import eidolon.api.app as app_module
    import eidolon.config as config

    config.get_settings.cache_clear()
    app_module._runtime = None
    return TestClient(app_module.app)


def test_health(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["profile"].startswith("general-continuity@")


def test_mint_resolve_replay_flow(client) -> None:
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()

    # Seed strong evidence via capture ingest so the twin can answer.
    consent = {"id": "c1", "principal_id": principal.public_key_hex, "source": "docs"}
    records = [
        {"content": "principal reports atlas status friday on track weekly", "provenance": "docs.read"}
        for _ in range(5)
    ]
    r = client.post("/capture/ingest", json={"consent": consent, "records": records})
    assert r.status_code == 200 and len(r.json()["ingested"]) == 5

    # Mint a root delegation covering answer-status on project atlas.
    params = {
        "principal_id": principal.public_key_hex,
        "issued_to": twin.public_key_hex,
        "scope": {"project": ["atlas"]},
        "permitted_classes": ["answer-status"],
        "escalation_required": ["commit-action"],
        "max_autonomy": "autonomous",
        "blast_radius_budget": {"scope_expansion": 0},
    }
    r = client.post("/delegations/mint", json={"signing_key": principal.signing_key_hex, "params": params})
    assert r.status_code == 200, r.text
    root = r.json()

    # Resolve an answer-status action.
    action = {
        "id": "a1",
        "action_class": "answer-status",
        "description": "answer atlas status friday on track weekly",
        "scope": {"selectors": {"project": ["atlas"]}},
    }
    context = {"principal_id": principal.public_key_hex, "query": "atlas status friday on track weekly"}
    # Twin is certified for answer-status at autonomous (certify-before-empower).
    certs = [{"action_class": "answer-status", "agreement": 1.0, "calibration": 1.0,
              "sample_size": 10, "ceiling": "autonomous"}]
    r = client.post(
        "/resolve",
        json={"action": action, "context": context, "chain": [root], "certificates": certs},
    )
    assert r.status_code == 200, r.text
    decision = r.json()
    assert decision["level"] == "AUTONOMOUS_ACT"
    assert decision["attestation_hash"]

    # Replay reconstructs the attestation.
    r = client.get("/replay", params={"principal_id": principal.public_key_hex})
    assert r.status_code == 200
    records = r.json()
    assert len(records) == 1
    assert records[0]["action_class"] == "answer-status"


def test_widening_attenuation_rejected_over_http(client) -> None:
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    sub = crypto.generate_keypair()
    params = {
        "principal_id": principal.public_key_hex,
        "issued_to": twin.public_key_hex,
        "scope": {"project": ["atlas"]},
        "permitted_classes": ["answer-status"],
        "max_autonomy": "draft",
        "blast_radius_budget": {"scope_expansion": 0},
    }
    root = client.post(
        "/delegations/mint", json={"signing_key": principal.signing_key_hex, "params": params}
    ).json()
    # Child tries to widen autonomy draft -> autonomous.
    child_params = {**params, "issued_to": sub.public_key_hex, "max_autonomy": "autonomous"}
    r = client.post(
        "/delegations/attenuate",
        json={"parent": root, "subset": child_params, "signing_key": twin.signing_key_hex},
    )
    assert r.status_code == 400
    assert "autonomy" in r.json()["detail"]
