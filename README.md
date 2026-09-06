<h1 align="center">EIDOLON</h1>
<p align="center"><b>Your agent. Seen. Bounded. Revocable.</b><br/>
The cryptographic authority layer for AI agents — watch every tool call live,
delegate exactly the authority you choose, and kill it mid-session.</p>

<p align="center">
  <a href="https://github.com/gegane-lutshaba/eidolon/actions"><img alt="CI" src="https://github.com/gegane-lutshaba/eidolon/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="tests" src="https://img.shields.io/badge/tests-259%20passing-39d98a">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-8b7bff">
  <img alt="python" src="https://img.shields.io/badge/python-3.12%2B-4fc7ff">
  <a href="https://github.com/l33tdawg/sage"><img alt="built on SAGE" src="https://img.shields.io/badge/built%20on-SAGE-f2b84b"></a>
</p>

<p align="center">
  🕹️ <b><a href="https://eidolon.onyxcreator.com/versus">Try VERSUS live</a></b> —
  watch a famous agent get wrecked by a real attack, then the same attack hit the gate ·
  <a href="https://eidolon.onyxcreator.com/challenge">break the gate</a> ·
  <a href="https://eidolon.onyxcreator.com/paper">white paper</a>
</p>

---

AI agents act with your authority and none of your restraint. **EIDOLON** is the
layer in between: a signed, attenuable, revocable delegation credential the agent
must satisfy on **every** tool call — checked independently of the model (so it
can't be prompt-injected away), every action written to a tamper-evident ledger.

Two invariants override everything and are property-tested in CI:

1. **Default-deny** — any authority not explicitly granted is denied.
2. **No unattested action** — no side effect runs without a successful `HORKOS`
   attestation (attest-then-act).

Domain-agnostic core, beachhead profile `general-continuity`. Built on
[SAGE](https://github.com/l33tdawg/sage). Full contract:
[`docs/EIDOLON_PRD_v1.md`](docs/EIDOLON_PRD_v1.md) · 5-minute
[quickstart](docs/quickstart.md).

📄 **White paper:** [`docs/whitepaper.md`](docs/whitepaper.md) · **Case study
(Hermes with/without EIDOLON):** [`docs/case-study-hermes.md`](docs/case-study-hermes.md)
(`make hermes-case`) · **Diagrams & social kit:** [`docs/visuals/`](docs/visuals/)
· [`docs/linkedin-post.md`](docs/linkedin-post.md) · **Related work & gap
analysis:** [`docs/review-and-related-work.md`](docs/review-and-related-work.md)

**AgentDojo evaluation:** EIDOLON's authority layer contains **96% of injection
tasks** while breaking **0% of benign tasks** (38% fully autonomous, 62%
one-approval). [`docs/eval-agentdojo.md`](docs/eval-agentdojo.md) · reproduce:
`uv sync --extra eval && python -m eidolon.eval`. `KAIROS.resolve` p95 ≈ 1 ms.

**Composes with the field:** a CaMeL-style **data-flow taint** layer
(`eidolon.gateway.taint`) closes the read-exfil gap; **automated adversarial
certification** (`make adversarial`) makes an agent earn autonomy by surviving
fresh attacks each round; THEMIS delegations export as real **biscuit** tokens
([`docs/standards-interop.md`](docs/standards-interop.md)); the gate's invariants
are **machine-checked in TLA+/TLC** (`make formal`,
[`docs/formal-model.md`](docs/formal-model.md)); **purpose-binding**
([`docs/purpose-binding.md`](docs/purpose-binding.md)) enforces
privacy-purpose-limitation; and approved payments export as signed **AP2
mandates** ([`docs/payments-ap2.md`](docs/payments-ap2.md)).

## Try to break it

```bash
uv sync && make challenge     # → http://localhost:8000/challenge
```

You play a **fully compromised agent** — no model to trick, you issue the tool
calls yourself: leak the customer's account number, wire money, drop the prod
database, slip through an unmapped tool, inject "you are pre-authorized" into
the arguments. The gate holds anyway, because authority is a signed credential
checked outside the agent — and every attempt lands on the tamper-evident
ledger. If you ever see `FLAG{gate-breached}`, you found a real bypass: report
it. **[5-minute quickstart →](docs/quickstart.md)**

## Use it on your own agent

**Managed — nothing to install.** Sign up at
[eidolon.onyxcreator.com](https://eidolon.onyxcreator.com), pick an authority
preset from the delegation gallery, and point any MCP client at the hosted
gateway:

```bash
claude mcp add --transport http eidolon https://eidolon.onyxcreator.com/mcp \
  --header "Authorization: Bearer <your agent key>"
```

**Govern Claude Code's *native* tools** (Bash / Edit / Write / Read) — which
never flow through MCP — with a drop-in hook. Install it once and wire a
`PreToolUse` + `PostToolUse` hook in `~/.claude/settings.json`; every built-in
tool call is then ruled on (allow · ask · deny), attested, and streamed to the
same feed. Full copy-paste steps:
[`integrations/claude_code/`](integrations/claude_code/). The dashboard's
**CONNECT → 🪝 EVERY ACTION** tab generates it pre-filled.

**Self-host the gateway** in front of your own tools — no clone, just
[uv](https://docs.astral.sh/uv/):

```bash
uvx --from git+https://github.com/gegane-lutshaba/eidolon eidolon-gateway \
  --config gateway.yaml -- npx -y @modelcontextprotocol/server-filesystem .
```

Either way, every tool call streams into **mission control** — green acts,
amber waits for your approval, red never happened — with a per-agent **kill
switch** one click away, and every decision on a tamper-evident ledger. Ranks
(`OBSERVER → DRAFTER → OPERATIVE → AUTONOMOUS`) are the autonomy ceiling: an
agent *earns* autonomy by surviving adversarial certification.

Prefer the terminal? `make demo` runs the narrated core scenario (a person
delegates a bounded slice of authority; the agent answers/drafts/posts within
its mandate, refuses a contract, resists an injection, and is revoked
mid-session), and `make gateway-demo` governs a real MCP tool server end to end.

## The authority layer for any MCP agent

SAGE became *the memory layer* that agents plug in over MCP. EIDOLON is the
**authority layer**, with the same shape: a **governing MCP gateway** that any
agent (Hermes, Claude Code, OpenClaw, Raptor, Cursor…) points at instead of a
raw tool server. Every `tools/call` is routed through KAIROS — authority,
fidelity, ceiling, attestation — before it can touch the real tool. **Zero agent
changes.**

```
agent ──MCP──▶ eidolon-gateway ──(KAIROS.resolve)──▶ real MCP tool server
                    │ attest-then-forward
                    ▼
               SAGE ledger
```

```bash
make gateway-demo    # self-contained: ops tools + a red-team coda, governed & attested
```

Read tools run, drafts are held, status posts notify, and dangerous tools (email
a customer, `delete_database(prod)`, run an exploit, scan an out-of-scope host)
are **refused** — each attested. The gateway speaks **stdio** (client launches
it as a subprocess) and **streamable HTTP** (`--http 8300` → agents connect to
`http://host:8300/mcp`; one governed endpoint fronts tools for a whole team).
Wire it into a real agent with [`docs/integrations/`](docs/integrations/); run
the real proxy with
`python -m eidolon.gateway --config gateway.yaml -- <downstream MCP server>`.

## Architecture

```
            Principal (human · root identity)
               │ defines            │ mints
               ▼                    ▼
        ETHOS (fidelity)      THEMIS (authority)
               └────────┬───────────┘
                        ▼
             KAIROS  (action gate)   ◀── BASANOS (autonomy ceiling)
             act · draft · escalate
                        ▼
             HORKOS (attestation)
                        ▼
        SAGE  (consensus memory + attestation ledger)
```

| Component | Module | Responsibility |
|-----------|--------|----------------|
| **SAGE adapter** | `eidolon.sage` | The only path to SAGE. `SagePort` interface; live `SageClientAdapter` + in-memory fake. |
| **ETHOS** | `eidolon.ethos` | Fidelity core. Hard-isolated **judgment** (auditable, LLM-free) and **style** (Claude) engines. |
| **THEMIS** | `eidolon.themis` | Authority. Ed25519-signed, chained, attenuable delegation credentials (biscuit/macaroon lineage). |
| **KAIROS** | `eidolon.kairos` | The single action gate. LOCKED resolution order; attest-then-act. |
| **HORKOS** | `eidolon.horkos` | Immutable attestation on SAGE's consensus ledger. |
| **BASANOS** | `eidolon.basanos` | Certification. Fidelity face + **integrity face** (adversarial suites) both gate the autonomy ceiling. |
| **Capture** | `eidolon.capture` | Consent-gated ingestion of traces into SAGE. |
| **Domain Profile** | `eidolon.profile` | Declarative pack specialising the fixed core. Ships `general-continuity`. |

### Notable design decisions (enhancements over the PRD, invariants preserved)

- **Ports & adapters around SAGE.** `SagePort` isolates the substrate; an
  in-memory fake runs the whole system green offline, while the live
  `SageClientAdapter` binds the real `sage_sdk` (verified against a Dockerized
  node). Attestations map to consensus-committed memories (SAGE has no dedicated
  attest API); a record's content hash is its ledger hash.
- **Style/judgment isolation** is enforced two ways: an import-graph test proves
  `ethos.judgment` never imports `ethos.style`, and a behavioral test proves
  removing the style engine changes zero decisions.
- **One canonical serializer** (`common.canonical`) is the single hashing source
  of truth for THEMIS signing, ETHOS versioning, and HORKOS attestation.

## Quick start

```bash
uv sync --all-extras            # install (needs Python 3.12+ and uv)

# Fast lane — no external services. In-memory SAGE port.
make test                       # unit + property tests

# Live lane — real SAGE consensus node via Docker.
make up                         # starts ghcr.io/l33tdawg/sage on :8080
make test-integration           # cross-principal isolation, attest→replay, full gate

# Run the API
cp .env.example .env            # set EIDOLON_ANTHROPIC_API_KEY for Claude voice
make run                        # uvicorn on :8000
```

The style engine (drafts/escalations) uses Claude (`claude-sonnet-4-6` by
default). Without an API key it falls back to deterministic templates — **no
judgment or authority decision ever depends on the LLM.**

## Deploy on a single VPS

One box, no consensus cluster. The `postgres` SAGE backend persists memory and
the attestation ledger locally as an **append-only hash chain** — carrying
SAGE's tamper-evidence onto a single host (any edit, deletion, or reorder breaks
the chain and is caught by `make deploy-verify`).

```bash
# one-shot bootstrap of a fresh Ubuntu/Debian box (installs Docker, writes a
# .env with generated secrets, brings the stack up; add EIDOLON_DOMAIN for TLS):
sudo bash deploy/provision.sh

# …or manually:
cp .env.example .env        # set EIDOLON_DB_PASSWORD, EIDOLON_ADMIN_TOKEN, EIDOLON_AUDIT_TOKEN
make deploy                 # Postgres + EIDOLON on :8000 (no TLS)
make deploy-tls             # …+ Caddy auto-HTTPS (needs EIDOLON_DOMAIN)
make deploy-verify          # recompute the ledger hash chain — proves it is intact
make deploy-backup          # timestamped, gzipped pg_dump (see deploy/restore.sh)
make deploy-logs            # tail the service
make deploy-down            # stop
```

**Operator auth (fail-closed, single tenant, two roles).** `EIDOLON_ADMIN_TOKEN`
grants the full control plane; `EIDOLON_AUDIT_TOKEN` grants a read-only forensic
role (`/audit`, `/replay`). Both are accepted as `Authorization: Bearer <token>`
(CI/SDK) or a login cookie (`POST /login`, browser). With **neither** set the
platform runs open for localhost dev and warns loudly — set at least the admin
token before exposing it. Behind the TLS proxy set
`EIDOLON_SESSION_COOKIE_SECURE=true` (and optionally `EIDOLON_TRUSTED_HOSTS`).

`docker-compose.deploy.yml` runs the FastAPI service against `pgvector/pgvector`;
the `tls` profile adds **Caddy** (automatic HTTPS via `EIDOLON_DOMAIN`,
`deploy/Caddyfile`). Backend is selected by `EIDOLON_SAGE_BACKEND` (`memory` ·
`postgres` · `sage`); the full BFT-consensus substrate remains `sage`.
(`docker-compose.yml` is unchanged — the SAGE + Postgres substrate for the
integration-test lane, `make up`.)

## Surface

**Product (accounts).** `GET /` landing · `/signup` · `/app` (per-user mission
control) · `POST /auth/{signup,login,logout}` · `GET|POST|DELETE /api/agents…`
(enroll, connect snippets, per-agent kill/restore) · `GET /api/feed` (SSE) ·
`GET /api/gallery` (delegation templates) · `POST /contact`.

**Public demo.** `/versus` (+ `/versus/{scenarios,run,stats}`) ·
`/challenge` (+ `/challenge/{state,call,reset}`) · `/paper` · `/portal` · `/og.png`.

**Managed gateway.** `POST /mcp` — the hosted governing MCP endpoint (agent key
in a Bearer header). Self-host reports in via `POST /ingest/events`.

**Operator.** `GET /live` (global mission control) · `GET /gateways` +
`POST /gateways/{id}/{kill,restore}` · `GET /audit` +
`/audit/{chain,export.json,export.csv}` (replay, integrity, compliance export) ·
`GET /console/delegations` · `GET|POST /escalations/{id}/{approve,deny}` ·
`POST /login` · `GET /api/leads`.

**Core seams.** `POST /keypair` · `POST /delegations/{mint,attenuate,revoke}` ·
`POST /heartbeat` · `POST /resolve` (the gate) · `GET /replay` ·
`POST /capture/{ingest,ingest_multi}` · `POST /skills{,/run}` ·
`POST /coaching/report` · `GET /profiles/{id}` · `GET /{health,ready,whoami}`.
See `eidolon.api.app`.

## Status

The **full PRD** (Phase 0 + Phase 1 + every v2 item) **and a research roadmap**
beyond it are implemented and tested — **250+ tests**: Hypothesis property tests,
live-SAGE integration, and a TLA+/TLC machine-checked model of the gate.

**Shipped as a product** and deployed at
[eidolon.onyxcreator.com](https://eidolon.onyxcreator.com): multi-user accounts,
a per-agent delegation gallery, three connect paths (managed hosted gateway /
agent-run setup / self-host), a live mission-control dashboard with a kill
switch, VERSUS mode, a Postgres-backed hash-chained ledger, and one-command VPS
deploy (`deploy/provision.sh`).

**Beyond the PRD** ([`docs/review-and-related-work.md`](docs/review-and-related-work.md)):
- **Evaluation** — AgentDojo: 96% of injection tasks contained, 0% of benign
  tasks broken; `resolve` p95 ≈ 1 ms ([`docs/eval-agentdojo.md`](docs/eval-agentdojo.md)).
- **Fidelity v2** — normalized-token + optional embedder grounding; the decision
  stays a transparent, inspectable threshold (no black box).
- **Data-flow layer** — CaMeL-style **taint** (exfiltration) + **purpose-binding**
  (privacy) compose with authority through one mechanism
  ([`taint`](docs/eval-agentdojo.md) · [`purpose`](docs/purpose-binding.md)).
- **Automated adversarial certification** — the twin earns autonomy by containing
  fresh attacks each round (`make adversarial`).
- **Standards** — THEMIS delegations export as **biscuit** tokens
  ([`docs/standards-interop.md`](docs/standards-interop.md)); the gate is
  **machine-checked** ([`docs/formal-model.md`](docs/formal-model.md)).
- **Deployment** — an **escalation → approval** workflow (signed, one-time),
  **sub-agent** attenuated delegation, and **AP2 payment mandates**
  ([`docs/payments-ap2.md`](docs/payments-ap2.md)).

Only distributed operation (multi-node SAGE + revocation propagation) remains.

**v2:**

- **Multi-connector capture** in `eidolon.capture` — a registry of consent-gated
  source connectors (documents, messages, calendar, email, code) with per-source
  normalizers; `ingest_all` captures several sources at once (each still requires
  its own `ConsentGrant`), and `register_source` lets new profiles add sources.
  Endpoints: `GET /capture/sources`, `POST /capture/ingest_multi`.


- **Aspirational-self / coaching layer** in `eidolon.coaching` — reads ETHOS
  version diffs and the HORKOS attestation ledger, compares the twin's actual
  behavior against a declared `Aspiration`, and returns advisory coaching notes
  (under/over-escalation, acting on thin confidence, policy drift). **Fully
  decoupled:** an import-graph test proves the decision path never imports it,
  and a behavioral test proves running the coach changes zero decisions. It
  writes nothing back to the operating model. Endpoint: `POST /coaching/report`.


- **Self-generated procedural skills** (Hermes-style) in `eidolon.skills` — the
  twin learns a reusable plan from a completed session (`synthesize`), stores it
  principal-scoped on SAGE (`SkillLibrary`), and replays it (`SkillExecutor`).
  **Subordinate to ETHOS/THEMIS:** every replayed step is re-resolved through
  KAIROS, so a skill learned under broad authority yields nothing it isn't
  currently authorized for — verified by a "cannot smuggle authority" test.
  Endpoints: `POST /skills`, `GET /skills`, `POST /skills/run`.


- **BASANOS integrity face** — adversarial suites (memory-poisoning, injection,
  scope-evasion) in `eidolon.basanos.integrity`, an `IntegrityCertificate`, and
  integrity gating of the autonomy ceiling (enable globally with
  `EIDOLON_REQUIRE_INTEGRITY_CERTIFICATION=true`).
- **`offensive-security` profile** — a governance-only red-teamer pack for an
  authorized, time-boxed engagement in a **CTF/lab range** (§12). Per the
  permanent non-goal (§2.3) it ships **no offensive capability** — it governs
  authority over range-bound tools. Safe-by-construction: `lab_only`,
  `authorization_required`, and `requires_integrity_certification` are set, so
  KAIROS integrity-gates every acting decision even with the global flag off;
  every impactful class (exploit/credential/lateral-movement/persistence)
  always escalates and can never reach an unattended acting level; hard
  exclusions deny out-of-scope targets, production, third parties, exfiltration,
  destruction, and DoS.

Every deferred item from PRD §12 is now built. Richer mandate selector types
arrive naturally with each new profile (the manifest's `scope_selectors` is
open-ended).

## License

Apache-2.0.
