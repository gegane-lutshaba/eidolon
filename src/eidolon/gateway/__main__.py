"""``python -m eidolon.gateway`` — run the governing MCP proxy.

Front a downstream MCP tool server, governed by a profile + policy:

    # stdio gateway (client launches this as a subprocess):
    python -m eidolon.gateway --config gateway.yaml \
        -- npx -y @modelcontextprotocol/server-filesystem /work

    # streamable-HTTP gateway (remote agents point at http://host:8300/mcp):
    python -m eidolon.gateway --config gateway.yaml --http 8300 \
        -- npx -y @modelcontextprotocol/server-filesystem /work

    # HTTP downstream instead of a stdio command:
    python -m eidolon.gateway --config gateway.yaml --http 8300 \
        --downstream-url http://localhost:9000/mcp

Everything after ``--`` is the downstream server command. Any MCP client
(Hermes, Claude Code, Cursor…) can point at the gateway on either transport.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import yaml

from eidolon.common import crypto
from eidolon.gateway.config import GatewayConfig
from eidolon.gateway.server import serve, serve_http


def _load_config(path: str | None) -> GatewayConfig:
    if path:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return GatewayConfig.model_validate(data)
    # No config → a minimal general-continuity gateway with a fresh principal
    # key (printed so it can be pinned). Handy for a quick trial.
    kp = crypto.generate_keypair()
    print(f"[eidolon-gateway] generated principal key {kp.public_key_hex}", file=sys.stderr)
    return GatewayConfig(profile_id="general-continuity", principal_signing_key=kp.signing_key_hex)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eidolon.gateway", description=__doc__)
    ap.add_argument("--config", help="path to a gateway.yaml")
    ap.add_argument("--http", type=int, metavar="PORT", default=None,
                    help="serve MCP over streamable HTTP on this port (endpoint /mcp)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind host for --http (default 127.0.0.1; 0.0.0.0 to expose)")
    ap.add_argument("--downstream-url", default=None,
                    help="downstream is a streamable-HTTP MCP server at this URL")
    ap.add_argument("downstream", nargs=argparse.REMAINDER,
                    help="downstream MCP server command (after --)")
    args = ap.parse_args(argv)

    downstream = [a for a in args.downstream if a != "--"]
    if not downstream and not args.downstream_url:
        ap.error("provide the downstream MCP server command after `--`, or --downstream-url")

    config = _load_config(args.config)
    cmd = downstream[0] if downstream else None
    rest = downstream[1:] if downstream else []
    if args.http is not None:
        asyncio.run(serve_http(cmd, rest, config, host=args.host, port=args.http,
                               downstream_url=args.downstream_url))
    else:
        asyncio.run(serve(cmd, rest, config, downstream_url=args.downstream_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
