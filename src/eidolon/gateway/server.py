"""EIDOLON governing MCP proxy server.

An MCP server that fronts a downstream MCP tool server. It re-exposes the
downstream tools unchanged, but every ``tools/call`` is governed by
:class:`~eidolon.gateway.engine.GovernanceEngine` (KAIROS) before it can reach
the real tool:

- an acting decision → forward to the downstream tool, return its result
  (attestation already written — attest-then-forward);
- draft / escalate / deny → return a structured refusal (``isError`` + the
  EIDOLON message + attestation hash), the real tool is never called.

Transports (mix and match):

- **serve** — speak MCP on stdio (for clients that launch the gateway as a
  subprocess: Claude Code, Cursor, Hermes…).
- **serve_http** — speak MCP over streamable HTTP on a port, so any remote
  agent points at ``http://host:port/mcp``. This is the deployment shape for
  the VPS: one governed endpoint for the whole team.
- The **downstream** may be a stdio command or a streamable-HTTP URL.

The ``mcp`` SDK is imported lazily so the governance core stays usable (and
testable) without it. Run via ``python -m eidolon.gateway`` (see __main__).
"""

from __future__ import annotations

import contextlib
from typing import Any

from eidolon.gateway.config import GatewayConfig, build_engine
from eidolon.gateway.engine import GovernanceEngine


@contextlib.asynccontextmanager
async def _downstream_session(command: str | None, args: list[str], url: str | None):
    """Connect the downstream tool server: stdio command or streamable-HTTP URL."""
    from mcp import ClientSession

    if url:
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(url) as (read, write, _get_sid):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(command=command, args=args)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def _build_server(engine: GovernanceEngine, downstream, tools, *, server_name: str):
    """The governed MCP server over an initialized downstream session."""
    import mcp.types as types
    from mcp.server import Server

    server: Server = Server(server_name)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        # Re-expose the downstream tools unchanged; governance is transparent
        # to the agent.
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict | None):
        return await _govern_and_forward(engine, downstream, name, arguments or {}, types)

    return server


async def serve(
    downstream_command: str,
    downstream_args: list[str],
    config: GatewayConfig,
    *,
    server_name: str = "eidolon-gateway",
    downstream_url: str | None = None,
) -> None:
    """Run the gateway over stdio, proxying a downstream MCP server."""
    from mcp.server.stdio import stdio_server

    engine = build_engine(config)
    async with _downstream_session(downstream_command, downstream_args, downstream_url) as downstream:
        tools = (await downstream.list_tools()).tools
        server = _build_server(engine, downstream, tools, server_name=server_name)
        init = server.create_initialization_options()
        async with stdio_server() as (r, w):
            await server.run(r, w, init)


async def serve_http(
    downstream_command: str | None,
    downstream_args: list[str],
    config: GatewayConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8300,
    server_name: str = "eidolon-gateway",
    downstream_url: str | None = None,
    _started: Any | None = None,  # optional anyio.Event for tests
) -> None:
    """Run the gateway over streamable HTTP (endpoint: ``/mcp``).

    Any MCP client with HTTP support connects to ``http://host:port/mcp``;
    every tools/call is governed and attested exactly as over stdio.
    """
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    engine = build_engine(config)
    async with _downstream_session(downstream_command, downstream_args, downstream_url) as downstream:
        tools = (await downstream.list_tools()).tools
        server = _build_server(engine, downstream, tools, server_name=server_name)
        manager = StreamableHTTPSessionManager(server, stateless=True)

        async with manager.run():
            async def app(scope, receive, send):
                if scope["type"] == "lifespan":
                    # uvicorn lifespan protocol — accept and idle.
                    while True:
                        message = await receive()
                        if message["type"] == "lifespan.startup":
                            await send({"type": "lifespan.startup.complete"})
                        elif message["type"] == "lifespan.shutdown":
                            await send({"type": "lifespan.shutdown.complete"})
                            return
                elif scope["type"] == "http" and scope["path"].rstrip("/") in ("/mcp", ""):
                    await manager.handle_request(scope, receive, send)
                else:
                    await send({"type": "http.response.start", "status": 404, "headers": []})
                    await send({"type": "http.response.body", "body": b"not found"})

            uv_config = uvicorn.Config(app, host=host, port=port, log_level="warning")
            uv_server = uvicorn.Server(uv_config)
            if _started is not None:
                # Signal readiness for tests once the socket is bound.
                orig_startup = uv_server.startup

                async def startup(**kw):
                    await orig_startup(**kw)
                    _started.set()

                uv_server.startup = startup
            await uv_server.serve()


async def _govern_and_forward(engine: GovernanceEngine, downstream, name, arguments, types):
    # Sync gate (attestation written here) …
    decision = engine.decide(name, arguments)
    meta = {"eidolon": {"action_class": decision.action_class, "level": decision.level,
                        "attestation_hash": decision.attestation_hash}}
    if not decision.allowed:
        # … refusal: the real tool is never called. isError results are not
        # schema-validated by clients, so the meta may ride structuredContent
        # too (back-compat for existing integrations).
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=decision.message or "denied")],
            structuredContent=meta, isError=True, _meta=meta,
        )
    # … acting: attest-then-forward to the real downstream tool.
    result = await downstream.call_tool(name, arguments)
    # Feed the output to the data-flow layer so a later egress carrying a
    # sensitive value it returned is caught as exfiltration.
    engine.observe_result(name, _result_text(result, types))
    content = list(result.content) if result.content else []
    content.append(types.TextContent(
        type="text", text=f"[EIDOLON: {decision.level} · attested {decision.attestation_hash}]"))
    # Preserve the downstream's structuredContent untouched — strict clients
    # validate it against the tool's declared outputSchema. EIDOLON metadata
    # travels in the namespaced `_meta` field instead.
    return types.CallToolResult(content=content,
                                structuredContent=result.structuredContent,
                                isError=bool(result.isError), _meta=meta)


def _result_text(result, types) -> str:
    """Flatten a downstream CallToolResult's text content for taint scanning."""
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)
