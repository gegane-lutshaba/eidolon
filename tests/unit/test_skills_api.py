"""Skills over HTTP: save -> list -> run through the API (subordinate to KAIROS)."""

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


def test_skill_save_list_run(client) -> None:
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    pid = principal.public_key_hex

    # seed grounding
    consent = {"id": "c1", "principal_id": pid, "source": "docs"}
    records = [{"content": "principal reports atlas status friday on track weekly", "provenance": "docs.read"}
               for _ in range(5)]
    client.post("/capture/ingest", json={"consent": consent, "records": records})

    # save a skill
    skill = {
        "name": "status recap",
        "description": "answer atlas status",
        "principal_id": pid,
        "profile_id": "general-continuity",
        "steps": [{
            "action_class": "answer-status",
            "description": "answer atlas status friday on track weekly",
            "scope": {"selectors": {"project": ["atlas"]}},
            "budget_cost": {},
        }],
    }
    r = client.post("/skills", json=skill)  # single body param = raw skill
    assert r.status_code == 200, r.text
    skill_id = r.json()["skill_id"]

    # list skills for the principal
    r = client.get("/skills", params={"principal_id": pid, "query": "atlas status"})
    assert r.status_code == 200
    assert any(s["id"] == skill_id for s in r.json())
    # isolation: another principal sees none
    assert client.get("/skills", params={"principal_id": "other", "query": "atlas status"}).json() == []

    # mint authority and run the skill
    params = {
        "principal_id": pid, "issued_to": twin.public_key_hex,
        "scope": {"project": ["atlas"]}, "permitted_classes": ["answer-status"],
        "escalation_required": ["commit-action"], "max_autonomy": "autonomous",
        "blast_radius_budget": {"scope_expansion": 0},
    }
    root = client.post("/delegations/mint",
                       json={"signing_key": principal.signing_key_hex, "params": params}).json()
    certs = [{"action_class": "answer-status", "agreement": 1.0, "calibration": 1.0,
              "sample_size": 10, "ceiling": "autonomous"}]
    context = {"principal_id": pid, "query": "answer atlas status friday on track weekly"}
    r = client.post("/skills/run", json={
        "skill": skill, "context": context, "chain": [root], "certificates": certs,
    })
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["completed"] is True
    assert run["outcomes"][0]["level"] == "AUTONOMOUS_ACT"
    assert run["outcomes"][0]["attestation_hash"]
