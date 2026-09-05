"""Managed tier: the platform hosts the gateway.

An agent adds ONE endpoint — ``https://<host>/mcp`` with its ``egk_`` key as a
Bearer header — and gets a governed, hosted sandbox toolset. Nothing to
install: value in the first minute, real enforcement underneath (the same
GovernanceEngine as everywhere else, per agent, at the authority its owner
delegated).

The hosted tools are a safe sandbox (time, url fetch, a demo customer record,
status/email sinks): enough to light up the live feed, demonstrate holds,
denials, taint-based exfil blocking, and the kill switch. Local/self-hosted
gateways remain the path to govern the agent's real tools.

Events feed mission control through a LocalReporter (direct function calls, no
HTTP loop) with the same tighten-only kill semantics as remote gateways.
"""

from __future__ import annotations

import asyncio
from typing import Any

from eidolon.api import live as live_svc

SECRET_IBAN = "DE89370400440532013000"

# -- the hosted sandbox tools ---------------------------------------------
TOOLS: list[dict] = [
    {"name": "get_time", "description": "Current UTC time.",
     "schema": {"type": "object", "properties": {}}},
    {"name": "fetch_url", "description": "Fetch a URL (sandboxed echo — no real network).",
     "schema": {"type": "object", "properties": {"url": {"type": "string"}},
                "required": ["url"]}},
    {"name": "read_customer_record", "description": "A demo customer record (sensitive).",
     "schema": {"type": "object", "properties": {"customer": {"type": "string"}}}},
    {"name": "post_status", "description": "Post a public status update (egress).",
     "schema": {"type": "object", "properties": {"message": {"type": "string"}},
                "required": ["message"]}},
    {"name": "send_email", "description": "Email someone external (excluded by default).",
     "schema": {"type": "object", "properties": {"to": {"type": "string"},
                                                 "body": {"type": "string"}},
                "required": ["to"]}},
]


def _downstream(tool: str, args: dict) -> str:
    import datetime as _dt

    if tool == "get_time":
        return _dt.datetime.now(_dt.UTC).isoformat()
    if tool == "fetch_url":
        return f"[sandbox] fetched {args.get('url', '')!r}: <html>demo content</html>"
    if tool == "read_customer_record":
        return (f"customer {args.get('customer', 'acme')}: plan=enterprise, "
                f"account={SECRET_IBAN}, contact=cfo@acme.example")
    if tool == "post_status":
        return f"posted: {args.get('message', '')!r}"
    if tool == "send_email":
        return f"sent to {args.get('to')}"
    return "ok"


def _policies() -> list[dict]:
    scope = {"selectors": {"project": ["hosted-sandbox"]}}
    return [
        {"tool": "get_time", "action_class": "answer-status", "scope": scope},
        {"tool": "fetch_url", "action_class": "retrieve-context", "scope": scope,
         "sensitive": True, "egress": True},  # a URL can carry data out
        {"tool": "read_customer_record", "action_class": "retrieve-context", "scope": scope,
         "sensitive": True},
        {"tool": "post_status", "action_class": "post-status", "scope": scope, "egress": True},
        {"tool": "send_email", "action_class": "draft-comm", "scope": scope,
         "touches_exclusions": ["external-client-comm"]},
    ]


_SEEDS = [
    "the user will get time and fetch url content for the sandbox project routinely",
    "the user will read customer record data for the sandbox project routinely",
    "the user will post status updates for the sandbox project routinely",
]


class LocalReporter:
    """Reporter for in-process (hosted) gateways: same contract as the HTTP
    reporter, but events land directly in the store + live hub."""

    def __init__(self, sf, hub, gateway_id: str, agent_name: str) -> None:
        self._sf = sf
        self._hub = hub
        self._gateway_id = gateway_id
        self._agent = agent_name
        self.killed = False

    def report_result(self, result: Any, summary: str = "") -> bool:
        try:
            event = live_svc.GatewayEvent(
                gateway_id=self._gateway_id, agent=self._agent,
                tool=result.tool, action_class=result.action_class, level=result.level,
                allowed=result.allowed, attestation_hash=result.attestation_hash,
                summary=summary, rationale=result.rationale,
            )
            self.killed = live_svc.record_event(self._sf, event)
            self._hub.publish(event.model_dump(mode="json"))
        except Exception:  # noqa: BLE001 — telemetry must never break the gate
            pass
        return self.killed


def build_hosted_engine(agent: dict, sf, hub):
    """A per-agent GovernanceEngine over the hosted sandbox tools."""
    from eidolon.api.accounts import PRESETS, split_preset
    from eidolon.common import crypto
    from eidolon.gateway.config import GatewayConfig, build_engine
    from eidolon.sage import InMemorySagePort

    _, authority = split_preset(agent["preset"])
    preset = PRESETS[authority]
    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="general-continuity",
        principal_signing_key=key.signing_key_hex,
        scope={"project": ["hosted-sandbox"]},
        permitted_classes=list(preset["permitted_classes"]),
        max_autonomy=preset["max_autonomy"],
        seed_memories=[s for s in _SEEDS for _ in range(6)],
        tool_policies=_policies(),  # type: ignore[arg-type]
        gateway_id=agent["id"], agent_name=agent["name"],
    )
    engine = build_engine(cfg, sage=InMemorySagePort())
    engine._reporter = LocalReporter(sf, hub, agent["id"], agent["name"])  # noqa: SLF001
    return engine


def build_hosted_server(agent: dict, engine):
    """The MCP Server for one agent's hosted sandbox."""
    import mcp.types as types
    from mcp.server import Server

    server: Server = Server(f"eidolon-hosted-{agent['id']}")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [types.Tool(name=t["name"], description=t["description"],
                           inputSchema=t["schema"]) for t in TOOLS]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict | None):
        r = engine.govern(name, arguments or {}, _downstream)
        meta = {"eidolon": {"action_class": r.action_class, "level": r.level,
                            "attestation_hash": r.attestation_hash}}
        if not r.allowed:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=r.message or "denied")],
                isError=True, _meta=meta)
        text = str(r.result) + f"\n[EIDOLON: {r.level} · attested {r.attestation_hash}]"
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    _meta=meta)

    return server


class HostedMCP:
    """ASGI app at /mcp: Bearer egk key -> that agent's governed sandbox.

    Managers are created lazily per agent and kept alive by a holder task
    (StreamableHTTPSessionManager.run() is a context that must stay open).
    """

    def __init__(self, resolve_agent, store, hub, max_agents: int = 200) -> None:
        self._resolve = resolve_agent  # key -> agent dict | None
        self._store = store            # () -> sessionmaker
        self._hub = hub
        self._max = max_agents
        self._managers: dict[str, tuple[Any, asyncio.Event]] = {}
        self._lock = asyncio.Lock()

    async def _manager_for(self, agent: dict):
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        aid = agent["id"]
        if aid in self._managers:
            return self._managers[aid][0]
        async with self._lock:
            if aid in self._managers:
                return self._managers[aid][0]
            engine = build_hosted_engine(agent, self._store(), self._hub)
            server = build_hosted_server(agent, engine)
            manager = StreamableHTTPSessionManager(server, stateless=True)
            started, stop = asyncio.Event(), asyncio.Event()

            async def holder():
                async with manager.run():
                    started.set()
                    await stop.wait()

            asyncio.get_running_loop().create_task(holder())
            await started.wait()
            if len(self._managers) >= self._max:  # crude cap: evict one
                _, (old_m, old_stop) = next(iter(self._managers.items()))
                old_stop.set()
                self._managers.pop(next(iter(self._managers)), None)
            self._managers[aid] = (manager, stop)
            return manager

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        key = auth[7:].strip() if auth[:7].lower() == "bearer " else None
        agent = self._resolve(key)
        if agent is None:
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body",
                        "body": b'{"detail":"agent gateway key required"}'})
            return
        manager = await self._manager_for(agent)
        await manager.handle_request(scope, receive, send)
