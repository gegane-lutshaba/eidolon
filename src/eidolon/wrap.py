"""``python -m eidolon.wrap`` — put EIDOLON in front of an existing agent config.

Reads an MCP client config (Claude Code / Cursor style ``.mcp.json``), rewrites
every tool server to run through the governing gateway, and backs up the
original. One command, zero agent changes:

    python -m eidolon.wrap                       # wraps ./.mcp.json in place
    python -m eidolon.wrap --mcp-json ~/.cursor/mcp.json --config gw.yaml

Already-wrapped entries are left alone, so re-running is safe.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

GATEWAY_MODULE = "eidolon.gateway"


def wrap_server(entry: dict, config: str, *, runner: str = "uv") -> dict:
    """Wrap one mcpServers entry so its command runs behind the gateway."""
    cmd = [entry.get("command", "")] + list(entry.get("args", []))
    prefix = (["uv", "run", "python"] if runner == "uv" else [sys.executable]) + [
        "-m", GATEWAY_MODULE, "--config", config, "--",
    ]
    wrapped = prefix + [c for c in cmd if c]
    out = dict(entry)
    out["command"] = wrapped[0]
    out["args"] = wrapped[1:]
    return out


def is_wrapped(entry: dict) -> bool:
    return GATEWAY_MODULE in (entry.get("args") or [])


def wrap_config(data: dict, config: str, *, runner: str = "uv") -> tuple[dict, list[str]]:
    """Wrap every unwrapped server; returns (new config, names wrapped)."""
    servers = data.get("mcpServers") or {}
    wrapped_names = []
    out_servers = {}
    for name, entry in servers.items():
        if is_wrapped(entry) or not entry.get("command"):
            out_servers[name] = entry
            continue
        out_servers[name] = wrap_server(entry, config, runner=runner)
        wrapped_names.append(name)
    return {**data, "mcpServers": out_servers}, wrapped_names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eidolon.wrap", description=__doc__)
    ap.add_argument("--mcp-json", default=".mcp.json", help="MCP client config to wrap")
    ap.add_argument("--config", default="gateway.yaml", help="gateway.yaml to govern with")
    ap.add_argument("--runner", choices=["uv", "python"], default="uv",
                    help="how the gateway is launched (uv run python | current python)")
    args = ap.parse_args(argv)

    path = pathlib.Path(args.mcp_json)
    if not path.exists():
        print(f"eidolon.wrap: {path} not found", file=sys.stderr)
        return 1
    if not pathlib.Path(args.config).exists():
        print(f"eidolon.wrap: warning — {args.config} not found; the wrapped servers "
              f"will need it at runtime (get it from your agent's CONNECT screen)",
              file=sys.stderr)

    data = json.loads(path.read_text(encoding="utf-8"))
    new_data, wrapped = wrap_config(data, args.config, runner=args.runner)
    if not wrapped:
        print("eidolon.wrap: nothing to wrap (all servers already governed)")
        return 0

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    path.write_text(json.dumps(new_data, indent=2) + "\n", encoding="utf-8")
    print(f"eidolon.wrap: governed {len(wrapped)} server(s): {', '.join(wrapped)}")
    print(f"eidolon.wrap: original backed up to {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
