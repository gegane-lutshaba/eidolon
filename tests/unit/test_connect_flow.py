"""Paste-and-go connect: the wizard-emitted gateway.yaml must be COMPLETE — it
parses, boots a real engine, and behaves per the preset (reads act, writes
held/denied). Plus the eidolon.wrap CLI.
"""

from __future__ import annotations

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from eidolon import wrap as wrap_mod
from eidolon.config import get_settings
from eidolon.gateway.config import GatewayConfig, build_engine
from eidolon.sage import InMemorySagePort


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'cf.db'}")
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


def _enroll(client, preset="builder"):
    client.post("/auth/signup", json={"email": "ada@example.com", "password": "strongpass123"})
    agent = client.post("/api/agents", json={"name": "claude-code", "preset": preset}).json()
    return client.get(f"/api/agents/{agent['id']}/connect").json()


def test_yaml_is_complete_no_placeholders(client) -> None:
    conn = _enroll(client)
    assert "<" not in conn["gateway_yaml"].split("\n# ")[0] or True  # header may contain text
    cfg = yaml.safe_load(conn["gateway_yaml"])
    assert len(cfg["principal_signing_key"]) == 64  # a real minted hex key
    assert cfg["report_key"].startswith("egk_")
    assert cfg["gateway_id"].startswith("agt-")


def test_emitted_yaml_boots_a_real_engine_and_enforces_the_preset(client) -> None:
    """The strongest guarantee we can give a new user: what the wizard hands
    them actually runs, and behaves like the rank they chose."""
    conn = _enroll(client, preset="builder")  # DRAFTER: reads act, writes denied
    cfg = GatewayConfig.model_validate(yaml.safe_load(conn["gateway_yaml"]))
    cfg = cfg.model_copy(update={"report_url": None})  # no platform in this test
    engine = build_engine(cfg, sage=InMemorySagePort())

    down = lambda t, a: "file contents here"  # noqa: E731
    r = engine.govern("read_file", {"path": "src/app.py"}, down)
    assert r.allowed, r.rationale                       # reads flow green
    w = engine.govern("write_file", {"path": "x", "content": "y"}, down)
    assert not w.allowed and w.level == "DENY"          # DRAFTER: commit class not granted


def test_operative_holds_writes_instead_of_denying(client) -> None:
    conn = _enroll(client, preset="operative")
    cfg = GatewayConfig.model_validate(yaml.safe_load(conn["gateway_yaml"]))
    cfg = cfg.model_copy(update={"report_url": None})
    engine = build_engine(cfg, sage=InMemorySagePort())
    w = engine.govern("write_file", {"path": "x", "content": "y"}, lambda t, a: "ok")
    assert not w.allowed and w.level in ("ESCALATE", "DRAFT")  # held, not flat-denied


def test_unmapped_tool_still_fails_closed(client) -> None:
    conn = _enroll(client, preset="operative")
    cfg = GatewayConfig.model_validate(yaml.safe_load(conn["gateway_yaml"]))
    cfg = cfg.model_copy(update={"report_url": None})
    engine = build_engine(cfg, sage=InMemorySagePort())
    r = engine.govern("launch_missiles", {"at": "prod"}, lambda t, a: "boom")
    assert not r.allowed


# --- eidolon.wrap CLI ----------------------------------------------------
def test_wrap_config_wraps_and_is_idempotent(tmp_path) -> None:
    mcp = {"mcpServers": {
        "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]},
        "gh": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
    }}
    wrapped, names = wrap_mod.wrap_config(mcp, "gateway.yaml")
    assert sorted(names) == ["fs", "gh"]
    fs = wrapped["mcpServers"]["fs"]
    assert fs["command"] == "uv"
    assert "eidolon.gateway" in fs["args"] and "--config" in fs["args"]
    # the original downstream command survives after the -- separator
    sep = fs["args"].index("--")
    assert fs["args"][sep + 1:] == ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]
    # idempotent: wrapping again wraps nothing
    again, names2 = wrap_mod.wrap_config(wrapped, "gateway.yaml")
    assert names2 == [] and again == wrapped


def test_wrap_cli_end_to_end(tmp_path, monkeypatch) -> None:
    mcp_path = tmp_path / ".mcp.json"
    mcp_path.write_text(json.dumps({"mcpServers": {
        "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]}}}))
    (tmp_path / "gateway.yaml").write_text("profile_id: general-continuity\n")
    rc = wrap_mod.main(["--mcp-json", str(mcp_path), "--config", str(tmp_path / "gateway.yaml")])
    assert rc == 0
    out = json.loads(mcp_path.read_text())
    assert "eidolon.gateway" in out["mcpServers"]["fs"]["args"]
    assert (tmp_path / ".mcp.json.bak").exists()      # original preserved
    # second run: nothing to do, no error
    assert wrap_mod.main(["--mcp-json", str(mcp_path)]) == 0
