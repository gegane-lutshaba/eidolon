"""EIDOLON governing MCP proxy server.

An MCP server that fronts a downstream MCP tool server. It re-exposes the
downstream tools unchanged, but every ``tools/call`` is governed by
:class:`~eidolon.gateway.engine.GovernanceEngine` (KAIROS) before it can reach
the real tool:

- an acting decision → forward to the downstream tool, return its result
  (attestation already written — attest-then-forward);
- draft / escalate / deny → return a structured refusal (``isError`` + the
  EIDOLON message + attestation hash), the real tool is never called.

The ``mcp`` SDK is imported lazily so the governance core stays usable (and
testable) without it. Run via ``python -m eidolon.gateway`` (see __main__).
"""

from __future__ import annotations

from eidolon.gateway.config import GatewayConfig, build_engine
from eidolon.gateway.engine import GovernanceEngine


async def serve(
    downstream_command: str,
    downstream_args: list[str],
    config: GatewayConfig,
    *,
    server_name: str = "eidolon-gateway",
) -> None:
    """Run the gateway over stdio, proxying a downstream stdio MCP server."""
    import mcp.types as types
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    engine = build_engine(config)

    params = StdioServerParameters(command=downstream_command, args=downstream_args)
    async with stdio_client(params) as (d_read, d_write):
        async with ClientSession(d_read, d_write) as downstream:
            await downstream.initialize()
            tools = (await downstream.list_tools()).tools

            server: Server = Server(server_name)

            @server.list_tools()
            async def _list_tools() -> list[types.Tool]:
                # Re-expose the downstream tools unchanged; governance is
                # transparent to the agent.
                return tools

            @server.call_tool()
            async def _call_tool(name: str, arguments: dict | None):
                return await _govern_and_forward(engine, downstream, name, arguments or {}, types)

            init = server.create_initialization_options()
            async with stdio_server() as (r, w):
                await server.run(r, w, init)


async def _govern_and_forward(engine: GovernanceEngine, downstream, name, arguments, types):
    # Sync gate (attestation written here) …
    decision = engine.decide(name, arguments)
    meta = {"eidolon": {"action_class": decision.action_class, "level": decision.level,
                        "attestation_hash": decision.attestation_hash}}
    if not decision.allowed:
        # … refusal: the real tool is never called.
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=decision.message or "denied")],
            structuredContent=meta, isError=True,
        )
    # … acting: attest-then-forward to the real downstream tool.
    result = await downstream.call_tool(name, arguments)
    content = list(result.content) if result.content else []
    content.append(types.TextContent(
        type="text", text=f"[EIDOLON: {decision.level} · attested {decision.attestation_hash}]"))
    return types.CallToolResult(content=content, structuredContent=meta,
                                isError=bool(result.isError))
