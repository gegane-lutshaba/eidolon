# Quickstart — see the gate hold in 5 minutes

Three ways in, fastest first. No account, no cloud: everything runs on your
machine (or your VPS).

## 1 · See it (2 minutes, nothing to configure)

```bash
git clone https://github.com/gegane-lutshaba/eidolon && cd eidolon
uv sync
make versus           # → open http://localhost:8000/versus
```

**VERSUS mode** runs a real-world attack twice: against a famous agent config
**without EIDOLON** (every call executes — data leaks, funds wire, the prod DB
drops, the HP bar hits zero) and the *same* attack **with EIDOLON** (the real
gate blocks it, live). Scenarios include a poisoned web page, zero-click inbox
exfiltration, a malicious dependency, RAG poisoning, and a rogue devops agent —
each credited to public research. Change the EIDOLON rank and watch the
right-hand side change with it: it's the production engine, not a script.

Or play it yourself at [eidolon.onyxcreator.com/versus](https://eidolon.onyxcreator.com/versus)
— no signup.

Why the gate holds: authority is a signed, attenuable credential checked outside
the agent (default-deny), reads are taint-tracked so their values cannot flow
out through egress tools, and no side effect runs without a ledger attestation.

## 2 · Govern your own agent (5 minutes)

The gateway is an MCP proxy: your agent points at it instead of the raw tool
server. Zero agent changes.

```bash
uv sync --extra mcp
```

**Claude Code / Cursor / Hermes (stdio)** — wrap any MCP server you already use:

```json
// .mcp.json (Claude Code) — same shape for Cursor / ~/.hermes/config.yaml
{
  "mcpServers": {
    "governed-fs": {
      "command": "uv",
      "args": ["run", "python", "-m", "eidolon.gateway", "--config", "gateway.yaml",
               "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/work"]
    }
  }
}
```

**Remote agents (streamable HTTP)** — one governed endpoint for a whole team:

```bash
python -m eidolon.gateway --config gateway.yaml --http 8300 --host 0.0.0.0 \
    -- npx -y @modelcontextprotocol/server-filesystem /work
# agents connect to http://your-host:8300/mcp
```

`gateway.yaml` declares who delegates what (see
[integrations](integrations/README.md) for the full recipe and per-agent
configs). Unmapped tools fail closed; excluded actions are denied; drafts and
escalations go to the approval inbox; everything is attested.

## 3 · Deploy the platform on a VPS (15 minutes)

```bash
sudo bash deploy/provision.sh     # installs Docker, generates secrets, starts the stack
# or: cp .env.example .env && make deploy      (make deploy-tls with EIDOLON_DOMAIN for HTTPS)
```

You get the full platform on one box: the **control plane** (mint / attenuate /
revoke delegations, approval inbox), the **audit console** (session replay,
denials & attacks view, ledger-integrity badge, SOC2/EU-AI-Act evidence
export), and the Postgres-backed **attestation ledger** — an append-only hash
chain; verify it any time with `make deploy-verify`. Operator auth is
fail-closed with two roles (admin / read-only auditor). Escalations and
revocations survive restarts.

## What you're looking at

| Guarantee | Mechanism |
|---|---|
| Default-deny | Ed25519-signed, attenuable delegation credentials (THEMIS) |
| No unattested action | attest-then-act through one gate (KAIROS → HORKOS) |
| Injection resistance | authority checked outside the model; arguments never widen it |
| Exfiltration blocked | CaMeL-style taint from sensitive reads to egress calls |
| Accountability | hash-chained ledger, replay, compliance export |

Numbers, if you want them: AgentDojo — **96% of injection tasks contained, 0%
of benign tasks broken**; the gate's invariants are machine-checked in TLA+;
`resolve` p95 ≈ 1 ms. [White paper](whitepaper.md) ·
[evaluation](eval-agentdojo.md) · [formal model](formal-model.md).
