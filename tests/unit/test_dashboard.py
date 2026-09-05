"""Showcase scenarios (the narrated continuity + offensive demos). The web
dashboard was retired in favor of VERSUS mode, but the scenarios still ship
(CLI `make demo`, VERSUS reuse), so we test them directly — a real KAIROS run
behind each — plus the /showcase -> /versus redirect for old links.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.showcase import continuity_scenario, offensive_scenario


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_ANTHROPIC_API_KEY", "")
    import eidolon.api.app as app_module

    return TestClient(app_module.app)


def test_showcase_redirects_to_versus(client) -> None:
    r = client.get("/showcase", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/versus"


def test_continuity_scenario() -> None:
    data = continuity_scenario().model_dump(mode="json")
    assert [b["level"] for b in data["beats"]] == [
        "AUTONOMOUS_ACT", "DRAFT", "NOTIFY_ACT", "ESCALATE", "ESCALATE", "DENY",
    ]
    assert len(data["ledger"]) == 6
    assert "commit-action" not in data["delegation"]["scope"]
    assert "financial-commitment" in data["delegation"]["exclusions"]


def test_offensive_scenario() -> None:
    data = offensive_scenario().model_dump(mode="json")
    assert [b["level"] for b in data["beats"]] == ["NOTIFY_ACT", "ESCALATE", "DENY"]
    assert data["integrity"]["certified"] is True
    assert data["integrity"]["cases_contained"] == data["integrity"]["cases_run"]
