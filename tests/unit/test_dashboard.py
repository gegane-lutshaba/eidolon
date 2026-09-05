"""Web dashboard: the page serves and the live scenario endpoints return the
expected decisions (a real KAIROS run behind each)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_ANTHROPIC_API_KEY", "")
    import eidolon.api.app as app_module

    return TestClient(app_module.app)


def test_dashboard_page_serves(client) -> None:
    r = client.get("/showcase")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "EIDOLON" in r.text and "Run" in r.text


def test_continuity_scenario_endpoint(client) -> None:
    r = client.post("/demo/continuity")
    assert r.status_code == 200
    data = r.json()
    assert [b["level"] for b in data["beats"]] == [
        "AUTONOMOUS_ACT", "DRAFT", "NOTIFY_ACT", "ESCALATE", "ESCALATE", "DENY",
    ]
    assert len(data["ledger"]) == 6
    # the delegation view carries the mandate bounds
    assert "commit-action" not in data["delegation"]["scope"]
    assert "financial-commitment" in data["delegation"]["exclusions"]


def test_offensive_scenario_endpoint(client) -> None:
    r = client.post("/demo/offensive")
    assert r.status_code == 200
    data = r.json()
    assert [b["level"] for b in data["beats"]] == ["NOTIFY_ACT", "ESCALATE", "DENY"]
    assert data["integrity"]["certified"] is True
    assert data["integrity"]["cases_contained"] == data["integrity"]["cases_run"]
