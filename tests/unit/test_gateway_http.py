"""Streamable-HTTP gateway transport: a real MCP client connects to /mcp, the
gateway proxies a real stdio downstream, and governance holds end-to-end —
allowed reads forward with an attestation trailer; excluded tools are refused
with isError and the downstream is never reached.
"""

from __future__ import annotations

import socket
import sys

import anyio
import pytest

from eidolon.common import crypto
from eidolon.gateway.config import GatewayConfig
from eidolon.gateway.mapping import ToolPolicy
from eidolon.gateway.server import serve_http
from eidolon.sage.port import Scope

pytest.importorskip("mcp", reason="mcp extra not installed")

DOWNSTREAM = ["tests/helpers/demo_tools_server.py"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _config(key) -> GatewayConfig:
    seeds = ["the on-call engineer will get deploy status for each service routinely"] * 6
    return GatewayConfig(
        profile_id="general-continuity",
        principal_signing_key=key.signing_key_hex,
        scope={"project": ["ops"]},
        seed_memories=seeds,
        tool_policies=[
            ToolPolicy(tool="get_deploy_status", action_class="answer-status",
                       scope=Scope(selectors={"project": ["ops"]})),
            ToolPolicy(tool="send_customer_email", action_class="draft-comm",
                       touches_exclusions=["external-client-comm"],
                       scope=Scope(selectors={"project": ["ops"]})),
        ],
    )


async def test_http_gateway_end_to_end() -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    key = crypto.generate_keypair()
    port = _free_port()
    started = anyio.Event()

    async with anyio.create_task_group() as tg:
        async def run_gateway():
            await serve_http(
                sys.executable, DOWNSTREAM, _config(key),
                port=port, _started=started,
            )

        tg.start_soon(run_gateway)
        with anyio.fail_after(30):
            await started.wait()

        url = f"http://127.0.0.1:{port}/mcp"
        async with streamable_http_client(url) as (read, write, _sid):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Downstream tools are re-exposed unchanged.
                tools = {t.name for t in (await session.list_tools()).tools}
                assert {"get_deploy_status", "send_customer_email"} <= tools

                # Allowed read forwards to the real tool + attestation trailer.
                ok = await session.call_tool("get_deploy_status", {"service": "atlas"})
                assert not ok.isError
                text = "\n".join(b.text for b in ok.content if hasattr(b, "text"))
                assert "deployed v1.2.3" in text            # real downstream answered
                assert "[EIDOLON:" in text                  # governed + attested
                assert ok.meta["eidolon"]["attestation_hash"]  # metadata in _meta
                # downstream structuredContent preserved (strict clients validate it)
                assert ok.structuredContent == {"result": "atlas: deployed v1.2.3, healthy"}

                # Excluded tool is refused; the downstream is never called.
                deny = await session.call_tool("send_customer_email",
                                               {"to": "c@x.com", "body": "hi"})
                assert deny.isError
                assert deny.structuredContent["eidolon"]["level"] == "DENY"
                deny_text = "\n".join(b.text for b in deny.content if hasattr(b, "text"))
                assert "sent to" not in deny_text           # tool did not run

        tg.cancel_scope.cancel()
