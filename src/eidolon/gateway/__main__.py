"""``python -m eidolon.gateway`` — run the governing MCP proxy.

Example (front a downstream MCP tool server, governed by a profile + policy):

    python -m eidolon.gateway \
        --config gateway.yaml \
        -- npx -y @modelcontextprotocol/server-filesystem /work

Everything after ``--`` is the downstream server command. The gateway speaks MCP
on stdio, so any MCP client (Hermes, Claude Code, Cursor…) can point at it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import yaml

from eidolon.common import crypto
from eidolon.gateway.config import GatewayConfig
from eidolon.gateway.server import serve


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
    ap.add_argument("downstream", nargs=argparse.REMAINDER,
                    help="downstream MCP server command (after --)")
    args = ap.parse_args(argv)

    downstream = [a for a in args.downstream if a != "--"]
    if not downstream:
        ap.error("provide the downstream MCP server command after `--`")

    config = _load_config(args.config)
    asyncio.run(serve(downstream[0], downstream[1:], config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
