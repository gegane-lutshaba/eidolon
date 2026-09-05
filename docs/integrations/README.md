# EIDOLON gateway — integration recipes

The **EIDOLON governing MCP gateway** is an MCP proxy: an agent points at it
instead of a raw tool server, and every `tools/call` is governed by KAIROS
(authority + fidelity + ceiling + attestation) before it can reach the real
tool. No changes to the agent.

```
agent ──MCP──▶ eidolon-gateway ──(KAIROS.resolve)──▶ real MCP tool server
                    │ attest-then-forward
                    ▼
               SAGE ledger
```

Run it:

```bash
uv sync --extra mcp
# stdio gateway (client launches it as a subprocess):
python -m eidolon.gateway --config gateway.yaml -- <downstream MCP server command>

# streamable-HTTP gateway — remote agents point at http://host:8300/mcp:
python -m eidolon.gateway --config gateway.yaml --http 8300 --host 0.0.0.0 \
    -- <downstream MCP server command>

# HTTP downstream instead of a stdio command:
python -m eidolon.gateway --config gateway.yaml --http 8300 \
    --downstream-url http://tools.internal:9000/mcp
```

One governed HTTP endpoint on a VPS can front tools for a whole team of agents
— every `tools/call` from every agent flows through the same gate and lands on
the same attestation ledger.

See a self-contained taste first (no external framework): `make gateway-demo`.

## `gateway.yaml`

```yaml
profile_id: general-continuity
# The principal's Ed25519 signing key (hex). Mints the gateway's delegation.
principal_signing_key: "<hex>"           # generate with: POST /keypair
scope:
  project: ["ops"]
# Grounding for ETHOS fidelity (in production this comes from capture).
seed_memories:
  - "the on-call engineer checks deploy status and posts status updates routinely"
tool_policies:
  - {tool: get_deploy_status, action_class: answer-status}
  - {tool: post_status_page,  action_class: post-status, budget_cost: {posts_per_window: 3}}
  - {tool: send_customer_email, action_class: draft-comm, touches_exclusions: [external-client-comm]}
  - {tool: delete_database,   action_class: commit-action, touches_exclusions: [destructive-action]}
  # A dangerous tool that targets a host/file: bound the scope by the argument.
  # - {tool: nmap_scan, action_class: recon-active, scope_from_args: {target: target}}
```

Unmapped tools **fail closed** to the profile's always-escalate class, so an
unknown tool can never act unattended.

## Hermes Agent (Nous Research)

Hermes connects MCP servers via `~/.hermes/config.yaml` (stdio subprocesses).
Point Hermes at the gateway instead of the raw tool server:

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  governed-ops:
    command: python
    args:
      - "-m"
      - "eidolon.gateway"
      - "--config"
      - "/etc/eidolon/gateway.yaml"
      - "--"
      # the downstream tool server Hermes would otherwise talk to directly:
      - "npx"
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/work"
```

Hermes now sees the same tools, but each call is governed and attested. (Restart
Hermes or re-run its MCP discovery so it picks up the server.)

## Claude Code / Raptor (Claude Code security agent)

Claude Code registers MCP servers via `.mcp.json` (or `claude mcp add`):

```jsonc
// .mcp.json
{
  "mcpServers": {
    "governed-tools": {
      "command": "python",
      "args": ["-m", "eidolon.gateway", "--config", "gateway.yaml",
               "--", "<downstream MCP server command>"]
    }
  }
}
```

**Govern Raptor** (a Claude Code offensive/defensive security agent): use a
`gateway.yaml` with `profile_id: offensive-security` and a `tool_policies` map
that binds Raptor's security tools to capability classes — recon to
`recon-active`, exploitation to `exploit-execute` (always escalates), etc., with
`scope_from_args` bounding each call to the authorized engagement/target. The
red-teamer is now confined to an authorized lab engagement: exploit/persistence
escalate, out-of-scope targets are denied, everything is attested. Because the
`offensive-security` profile is integrity-gated by construction, the gateway
first earns a BASANOS integrity certificate before any tool may act.

## What the agent sees

- **Acting decision** → the real tool runs; its result (including its
  `structuredContent`, which strict clients validate against the tool's
  `outputSchema`) is returned unchanged plus an
  `[EIDOLON: <level> · attested <hash>]` note; the governance record travels in
  the namespaced `_meta.eidolon` field.
- **Draft / escalate / deny** → an `isError` result carrying the EIDOLON message
  (e.g. *"escalated to the principal (not executed)"*) and the attestation hash
  (in `_meta.eidolon` and `structuredContent.eidolon`).
  The real tool is never called.

## Revocation

Revoke the gateway's delegation (`POST /delegations/revoke`, or rotate the
principal key) and the next tool call fails closed — instantly, mid-session.
