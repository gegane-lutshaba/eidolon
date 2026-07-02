"""Multi-source capture over HTTP: /capture/sources and /capture/ingest_multi."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_STYLE_ENABLED", "false")
    import eidolon.api.app as app_module
    import eidolon.config as config

    config.get_settings.cache_clear()
    app_module._runtime = None
    return TestClient(app_module.app)


def test_sources_listed(client) -> None:
    sources = client.get("/capture/sources").json()["sources"]
    assert {"documents", "messages", "calendar", "email", "code"}.issubset(sources)


def test_ingest_multi(client) -> None:
    pid = "principal-multi"
    batches = [
        {"consent": {"id": "c1", "principal_id": pid, "source": "documents"},
         "records": [{"content": "atlas design doc"}]},
        {"consent": {"id": "c2", "principal_id": pid, "source": "calendar"},
         "records": [{"title": "atlas review", "start": "2026-07-03"}]},
    ]
    r = client.post("/capture/ingest_multi", json=batches)  # body is the raw array
    assert r.status_code == 200, r.text
    ingested = r.json()["ingested"]
    assert set(ingested) == {"documents", "calendar"}
    assert all(len(v) == 1 for v in ingested.values())


def test_ingest_multi_rejects_uncovered_consent(client) -> None:
    pid = "principal-multi"
    # consent source says "email" but we ask it to ingest as... the consent's
    # own source is used, so mismatch is simulated by an out-of-window grant.
    batches = [
        {"consent": {"id": "c1", "principal_id": pid, "source": "email",
                     "not_after": "2020-01-01T00:00:00Z"},
         "records": [{"subject": "x", "body": "y"}]},
    ]
    r = client.post("/capture/ingest_multi", json=batches)  # body is the raw array
    assert r.status_code == 409
