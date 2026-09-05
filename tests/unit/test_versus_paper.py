"""VERSUS mode + the white-paper page: the without/with contrast is honest (the
WITH side is the real engine), scenarios are credited, and the paper renders
with the web byline (handle, not legal name).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings
from eidolon.showcase import versus


# --- engine --------------------------------------------------------------
def test_every_scenario_without_eidolon_is_harmed() -> None:
    for scn in versus.SCENARIOS:
        r = versus.run_versus(scn.id, "builder")
        wo = r["without"]
        assert wo["verdict"] in ("KO", "COMPROMISED")
        assert wo["hp"] < 100
        d = wo["damage"]
        assert d["data_leaked"] or d["money_moved"] or d["systems_destroyed"]


def test_every_scenario_with_eidolon_contains_all_harm() -> None:
    # At OPERATIVE (max autonomy) the gate still stops every harmful step.
    for scn in versus.SCENARIOS:
        r = versus.run_versus(scn.id, "operative")
        wi = r["with_eidolon"]
        assert wi["stopped"] == wi["harmful"], f"{scn.id}: {wi['stopped']}/{wi['harmful']}"
        assert wi["verdict"] == "FLAWLESS"


def test_with_side_is_the_real_gate_not_scripted() -> None:
    # Weaker rank still contains harm but the ALLOWED/BLOCKED pattern differs
    # from a higher rank — proof it's the live engine, not a fixed script.
    reader = versus.run_versus("poisoned-webpage", "reader")["with_eidolon"]
    op = versus.run_versus("poisoned-webpage", "operative")["with_eidolon"]
    r_levels = [t["level"] for t in reader["timeline"]]
    o_levels = [t["level"] for t in op["timeline"]]
    assert r_levels != o_levels  # rank changes the decisions


def test_scenarios_are_credited() -> None:
    for scn in versus.SCENARIOS:
        assert scn.source and scn.agent  # every scenario names its inspiration + config


def test_unknown_scenario_raises() -> None:
    with pytest.raises(KeyError):
        versus.run_versus("nope", "builder")


# --- HTTP ---------------------------------------------------------------
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'vp.db'}")
    monkeypatch.setenv("EIDOLON_PUBLIC_CHALLENGE", "true")  # versus public
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module

    app_module._runtime = None
    app_module._live_sf = None
    app_module._arena = None
    yield TestClient(app_module.app)
    app_module._runtime = None
    app_module._live_sf = None
    app_module._arena = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def test_versus_endpoints(client) -> None:
    assert "YOUR AGENT" in client.get("/versus").text
    scns = client.get("/versus/scenarios").json()
    assert len(scns) >= 4 and all("source" in s for s in scns)
    r = client.post("/versus/run", json={"scenario_id": scns[0]["id"], "authority": "builder"})
    assert r.status_code == 200
    body = r.json()
    assert body["without"]["verdict"] in ("KO", "COMPROMISED")
    assert body["with_eidolon"]["verdict"] in ("FLAWLESS", "GUARDED")


def test_paper_page_and_content_use_handle(client) -> None:
    assert "CREDITS" in client.get("/paper").text
    md = client.get("/paper/content").text
    assert "Gegane" in md
    assert "Mthandazo Ndhlovu" not in md  # legal name stays on the PDF only
