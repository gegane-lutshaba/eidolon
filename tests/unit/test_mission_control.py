"""Mission control: gateway event ingest + kill switch + live feed, and the
gateway reporter's tighten-only semantics (telemetry never weakens the gate;
the kill switch blocks the next action; an unreachable platform changes
nothing).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.api import live as live_svc
from eidolon.config import get_settings

EVENT = {
    "gateway_id": "gw-1", "agent": "claude-code", "tool": "send_email",
    "action_class": "draft-comm", "level": "DENY", "allowed": False,
    "attestation_hash": "abc123", "summary": "to=x@y.z", "rationale": "excluded",
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'mc.db'}")
    monkeypatch.setenv("EIDOLON_ADMIN_TOKEN", "admin-t")
    monkeypatch.setenv("EIDOLON_AUDIT_TOKEN", "audit-t")
    monkeypatch.setenv("EIDOLON_GATEWAY_KEYS", "gw-key-1,gw-key-2")
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module

    app_module._runtime = None
    app_module._live_sf = None
    yield TestClient(app_module.app)
    app_module._runtime = None
    app_module._live_sf = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


# --- ingest auth --------------------------------------------------------
def test_ingest_requires_gateway_key(client) -> None:
    assert client.post("/ingest/events", json=EVENT).status_code == 401
    assert client.post("/ingest/events", json=EVENT,
                       headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.post("/ingest/events", json=EVENT,
                    headers={"Authorization": "Bearer gw-key-1"})
    assert r.status_code == 200 and r.json() == {"ok": True, "killed": False}
    # auditor token is NOT a gateway credential
    assert client.post("/ingest/events", json=EVENT,
                       headers={"Authorization": "Bearer audit-t"}).status_code == 401


def test_feed_and_gateway_cards(client) -> None:
    gw = {"Authorization": "Bearer gw-key-1"}
    client.post("/ingest/events", json=EVENT, headers=gw)
    client.post("/ingest/events", json={**EVENT, "tool": "read_file",
                                        "level": "AUTONOMOUS_ACT", "allowed": True}, headers=gw)
    aud = {"Authorization": "Bearer audit-t"}
    cards = client.get("/gateways", headers=aud).json()
    assert cards[0]["id"] == "gw-1" and cards[0]["events"] == 2 and not cards[0]["killed"]
    feed = client.get("/live/recent", headers=aud).json()
    assert [e["tool"] for e in feed] == ["send_email", "read_file"]
    assert client.get("/live", headers=aud).status_code == 200  # page serves for auditor


# --- kill switch --------------------------------------------------------
def test_kill_flag_round_trip(client) -> None:
    gw = {"Authorization": "Bearer gw-key-1"}
    adm = {"Authorization": "Bearer admin-t"}
    client.post("/ingest/events", json=EVENT, headers=gw)

    assert client.post("/gateways/gw-1/kill", headers=adm).json()["killed"] is True
    r = client.post("/ingest/events", json=EVENT, headers=gw)
    assert r.json()["killed"] is True          # the gateway learns on next report

    assert client.post("/gateways/gw-1/restore", headers=adm).json()["killed"] is False
    assert client.post("/ingest/events", json=EVENT, headers=gw).json()["killed"] is False


def test_kill_is_admin_only(client) -> None:
    gw = {"Authorization": "Bearer gw-key-1"}
    client.post("/ingest/events", json=EVENT, headers=gw)
    r = client.post("/gateways/gw-1/kill", headers={"Authorization": "Bearer audit-t"})
    assert r.status_code == 403
    assert client.post("/gateways/nope/kill",
                       headers={"Authorization": "Bearer admin-t"}).status_code == 404


# --- reporter semantics (engine side) ------------------------------------
class FakeReporter:
    """Stands in for the HTTP reporter: scripted kill responses."""

    def __init__(self) -> None:
        self.killed = False
        self.events: list[dict] = []
        self.next_killed = False

    def report_result(self, result, summary: str = "") -> bool:
        self.events.append({"tool": result.tool, "level": result.level,
                            "allowed": result.allowed})
        self.killed = self.next_killed
        return self.killed


def _engine(reporter):
    from eidolon.common import crypto
    from eidolon.gateway.config import GatewayConfig, build_engine
    from eidolon.gateway.mapping import ToolPolicy
    from eidolon.sage import InMemorySagePort
    from eidolon.sage.port import Scope

    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="general-continuity", principal_signing_key=key.signing_key_hex,
        scope={"project": ["ops"]},
        seed_memories=["the on-call engineer will get deploy status for each service routinely"] * 6,
        tool_policies=[ToolPolicy(tool="get_deploy_status", action_class="answer-status",
                                  scope=Scope(selectors={"project": ["ops"]}))],
    )
    engine = build_engine(cfg, sage=InMemorySagePort())
    engine._reporter = reporter  # inject the fake
    return engine


def test_reporter_receives_every_decision_and_gate_unchanged() -> None:
    rep = FakeReporter()
    engine = _engine(rep)
    r = engine.govern("get_deploy_status", {"service": "atlas"}, lambda t, a: "ok")
    assert r.allowed and r.result == "ok"
    assert rep.events == [{"tool": "get_deploy_status", "level": "AUTONOMOUS_ACT", "allowed": True}]


def test_kill_blocks_before_forward_then_refuses_all() -> None:
    rep = FakeReporter()
    engine = _engine(rep)
    ran = []
    rep.next_killed = True  # platform says: killed (as of this report)
    r = engine.govern("get_deploy_status", {"service": "atlas"}, lambda t, a: ran.append(t))
    assert not r.allowed and ran == []          # blocked BEFORE the side effect
    # subsequent calls short-circuit as KILLED (still reported)
    r2 = engine.govern("get_deploy_status", {"service": "atlas"}, lambda t, a: ran.append(t))
    assert r2.level == "KILLED" and not r2.allowed and ran == []
    assert rep.events[-1]["level"] == "KILLED"
    # restore: platform stops saying killed -> next call acts again
    rep.next_killed = False
    engine.govern("get_deploy_status", {"service": "atlas"}, lambda t, a: ran.append(t))
    r3 = engine.govern("get_deploy_status", {"service": "atlas"}, lambda t, a: ran.append(t))
    assert r3.allowed and ran == ["get_deploy_status"]


def test_unreachable_platform_never_breaks_the_gate() -> None:
    from eidolon.gateway.reporter import Reporter

    rep = Reporter("http://127.0.0.1:1", key="x", timeout=0.2)  # nothing listens
    engine = _engine(rep)
    r = engine.govern("get_deploy_status", {"service": "atlas"}, lambda t, a: "ok")
    assert r.allowed and r.result == "ok"       # telemetry loss = dashboard dims, gate holds
    assert rep.killed is False


# --- live hub -----------------------------------------------------------
async def test_hub_fanout_and_backlog() -> None:
    hub = live_svc.LiveHub(replay=10)
    hub.publish({"n": 1})
    sid, queue, backlog = hub.subscribe()
    assert backlog == [{"n": 1}]                # replay on connect
    hub.publish({"n": 2})
    assert await queue.get() == {"n": 2}        # live fan-out
    hub.unsubscribe(sid)
    hub.publish({"n": 3})                        # no crash after unsubscribe
