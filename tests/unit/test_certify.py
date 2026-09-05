"""Certification-as-a-service: run the VERSUS attack library at an agent's
authority, issue a public certificate + badge, and expose it in the directory.
Honest: a certificate reflects the real gate (containment across the library).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'cert.db'}")
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module

    app_module._runtime = None
    app_module._live_sf = None
    app_module._login_hits.clear()
    yield TestClient(app_module.app)
    app_module._runtime = None
    app_module._live_sf = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def _agent(client, preset="coding/operative"):
    client.post("/auth/signup", json={"email": "ada@example.com", "password": "strongpass123"})
    return client.post("/api/agents", json={"name": "claude-code", "preset": preset}).json()


def test_certify_operative_is_certified(client) -> None:
    agent = _agent(client, "coding/operative")
    r = client.post(f"/api/agents/{agent['id']}/certify")
    assert r.status_code == 200
    cert = r.json()
    assert cert["status"] == "CERTIFIED"                 # OPERATIVE contains all harm
    assert cert["contained"] == cert["total"] >= 6
    assert cert["id"].startswith("cert-")


def test_certificate_is_public_with_scorecard_and_badge(client) -> None:
    agent = _agent(client)
    cert = client.post(f"/api/agents/{agent['id']}/certify").json()
    cid = cert["id"]

    # public JSON scorecard — no auth (crawlers/badges are anonymous)
    logged_out = TestClient(client.app)  # fresh, no cookies
    data = logged_out.get(f"/certified/{cid}.json")
    assert data.status_code == 200
    body = data.json()
    assert len(body["results"]) == body["total"]
    assert all("source" in x and "without_verdict" in x for x in body["results"])

    # scorecard page + directory serve
    assert "certificate" in logged_out.get(f"/certified/{cid}").text.lower()
    assert "CERTIFIED AGENTS" in logged_out.get("/certified").text

    # embeddable badge
    badge = logged_out.get(f"/certified/{cid}/badge.svg")
    assert badge.status_code == 200
    assert badge.headers["content-type"].startswith("image/svg")
    assert "EIDOLON" in badge.text


def test_certificate_appears_in_directory(client) -> None:
    agent = _agent(client)
    cid = client.post(f"/api/agents/{agent['id']}/certify").json()["id"]
    listing = client.get("/certified/list").json()
    assert any(c["id"] == cid for c in listing)


def test_certify_requires_owning_the_agent(client) -> None:
    agent = _agent(client)
    client.post("/auth/logout")
    client.cookies.clear()
    client.post("/auth/signup", json={"email": "bob@example.com", "password": "strongpass123"})
    assert client.post(f"/api/agents/{agent['id']}/certify").status_code == 404


def test_unknown_certificate_404(client) -> None:
    assert client.get("/certified/cert-nope.json").status_code == 404
    assert client.get("/certified/cert-nope/badge.svg").status_code == 404
