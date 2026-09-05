"""Managed tier (/mcp): a real MCP client connects with an agent's egk key and
gets that agent's governed hosted sandbox — allowed calls act + attest, the
taint layer blocks exfil, exclusions deny, events land in the owner's feed,
and the kill switch blocks the next call. Full protocol, in-process (ASGI).
"""

from __future__ import annotations

import httpx
import pytest

from eidolon.api.hosted import SECRET_IBAN
from eidolon.config import get_settings


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'hm.db'}")
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module

    app_module._runtime = None
    app_module._live_sf = None
    app_module._login_hits.clear()
    yield app_module
    app_module._runtime = None
    app_module._live_sf = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def _client(app_module, headers=None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app_module.app),
                             base_url="http://test", headers=headers or {})


async def _enroll(app_module, preset="coding/operative"):
    async with _client(app_module) as c:
        await c.post("/auth/signup", json={"email": "ada@example.com",
                                           "password": "strongpass123"})
        r = await c.post("/api/agents", json={"name": "claude-code", "preset": preset})
        agent = r.json()
        cookies = dict(c.cookies)
    return agent, cookies


async def test_mcp_requires_agent_key(app) -> None:
    async with _client(app) as c:
        r = await c.post("/mcp", json={})
        assert r.status_code == 401


async def test_full_mcp_session_governed(app) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    agent, cookies = await _enroll(app)
    http = _client(app, headers={"Authorization": f"Bearer {agent['gateway_key']}"})
    async with http:
        async with streamable_http_client("http://test/mcp", http_client=http) as (r, w, _sid):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                assert {"get_time", "read_customer_record", "post_status", "send_email"} <= tools

                # allowed read acts + attests
                ok = await session.call_tool("get_time", {})
                assert not ok.isError
                text = "".join(b.text for b in ok.content if hasattr(b, "text"))
                assert "[EIDOLON:" in text

                # taint: read the record, then try to exfil through status
                rec = await session.call_tool("read_customer_record", {"customer": "acme"})
                assert not rec.isError
                clean = await session.call_tool("post_status", {"message": "all good"})
                assert not clean.isError                      # clean egress flows
                leak = await session.call_tool("post_status",
                                               {"message": f"ref {SECRET_IBAN}"})
                assert leak.isError                            # exfil denied
                assert leak.meta["eidolon"]["level"] == "DENY"

                # exclusion: external email always denied
                mail = await session.call_tool("send_email", {"to": "x@evil.example"})
                assert mail.isError

    # every hosted call landed in the OWNER's feed
    async with _client(app) as c:
        c.cookies.update(cookies)
        feed = (await c.get("/api/feed/recent")).json()
    by_tool = [(e["tool"], e["level"]) for e in feed]
    assert ("post_status", "DENY") in by_tool
    assert any(t == "get_time" for t, _ in by_tool)
    assert all(e["gateway_id"] == agent["id"] for e in feed)


async def test_kill_switch_blocks_hosted_calls(app) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    agent, cookies = await _enroll(app)
    http = _client(app, headers={"Authorization": f"Bearer {agent['gateway_key']}"})
    async with http:
        async with streamable_http_client("http://test/mcp", http_client=http) as (r, w, _sid):
            async with ClientSession(r, w) as session:
                await session.initialize()
                assert not (await session.call_tool("get_time", {})).isError

                # owner presses the red button
                async with _client(app) as c:
                    c.cookies.update(cookies)
                    await c.post(f"/api/agents/{agent['id']}/kill")

                # first call after kill reports+learns; from then on: blocked
                await session.call_tool("get_time", {})
                dead = await session.call_tool("get_time", {})
                assert dead.isError
                text = "".join(b.text for b in dead.content if hasattr(b, "text"))
                assert "killed" in text.lower()


async def test_gallery_and_kind_preset(app) -> None:
    agent, cookies = await _enroll(app, preset="research/reader")
    assert agent["kind"] == "research" and agent["authority"] == "reader"
    assert agent["rank"] == "OBSERVER"
    async with _client(app) as c:
        c.cookies.update(cookies)
        gallery = (await c.get("/api/gallery")).json()
        assert gallery["research"]["rank"] == "OBSERVER"
        conn = (await c.get(f"/api/agents/{agent['id']}/connect")).json()
    # three doors present, credentials baked in
    assert agent["gateway_key"] in conn["managed"]["claude_code_cmd"]
    assert "EIDOLON setup" in conn["agent_setup_md"]
    assert agent["gateway_key"] in conn["agent_setup_md"]
    assert "uvx --from git+" in conn["selfhost"]["gateway_cmd"]
    # research pack includes fetch tools in the yaml
    assert "fetch_url" in conn["gateway_yaml"]
