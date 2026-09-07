# EIDOLON on-prem (Docker)

Run one EIDOLON on your own infrastructure and route every developer's agent
through it: one governed choke point, one tamper-evident ledger, per-agent kill
switches, org-wide policy, and downloadable compliance packs — nothing leaves
your network.

There are two ways to run it. Both are Docker.

---

## Tier 1 — Try it (one container, ~60s)

A single container for evaluation. Uses a SQLite operational store (mount a
volume to keep it) and an in-memory attestation ledger. Great for a demo; **not**
for production (the tamper-evident ledger needs Postgres — see Tier 2).

```bash
docker run -d --name eidolon -p 8000:8000 \
  -v eidolon-data:/data \
  ghcr.io/gegane-lutshaba/eidolon:latest
```

Open `http://localhost:8000`, sign up, enroll an agent. Before exposing it to
anyone else, set an admin token:

```bash
docker run -d --name eidolon -p 8000:8000 -v eidolon-data:/data \
  -e EIDOLON_ADMIN_TOKEN="$(openssl rand -hex 32)" \
  ghcr.io/gegane-lutshaba/eidolon:latest
```

---

## Tier 2 — Run it for real (Docker Compose, persistent ledger)

App + Postgres-backed SAGE port, so the attestation ledger is hash-chained and
tamper-evident on disk. This is the production shape.

```bash
# 1. Grab the compose file and the env template
curl -O https://raw.githubusercontent.com/gegane-lutshaba/eidolon/main/docker-compose.deploy.yml
curl -o .env https://raw.githubusercontent.com/gegane-lutshaba/eidolon/main/.env.example

# 2. Set at least these in .env
#    EIDOLON_DB_PASSWORD=<strong>          # Postgres password
#    EIDOLON_ADMIN_TOKEN=<openssl rand -hex 32>   # operator control plane
#    EIDOLON_PUBLIC_URL=https://eidolon.yourco.internal   # deep links + connect snippets

# 3. Bring it up (pulls the published image — no build needed)
docker compose -f docker-compose.deploy.yml up -d
```

Upgrade later with `docker compose -f docker-compose.deploy.yml pull && \
docker compose -f docker-compose.deploy.yml up -d`.

### TLS

The compose ships an optional Caddy reverse proxy with automatic HTTPS. Point a
DNS record at the box, then:

```bash
EIDOLON_DOMAIN=eidolon.yourco.internal EIDOLON_SESSION_COOKIE_SECURE=true \
  docker compose -f docker-compose.deploy.yml --profile tls up -d
```

Or terminate TLS at your own load balancer / ingress and route to the container's
port `8000`.

---

## Point your agents at it

Every developer sets one variable — the rest is the same as the hosted docs.

- **Claude Code, native tools:** the [hook](../integrations/claude_code/) with
  `EIDOLON_URL=https://eidolon.yourco.internal` and the agent's `egk_` key.
- **Any MCP client:** add `https://eidolon.yourco.internal/mcp` (Bearer the
  agent's key), or wrap existing MCP servers with `python -m eidolon.wrap`
  ([recipes](integrations/README.md)).

Admins govern from `/app`: live feed, per-agent kill switch, **🛡 org policy**
(blocked paths, egress allowlist, must-approve classes), the **governance
posture** dashboard, and hash-sealed **compliance packs**.

---

## Ops

| Concern | How |
|---|---|
| **Runs as non-root** | the image runs as uid 10001 (`eidolon`); `/data` is the only writable path in trial mode |
| **Health** | `HEALTHCHECK` hits `/health`; `docker inspect --format '{{.State.Health.Status}}' eidolon` |
| **Backups** | `deploy/backup.sh` dumps Postgres; `deploy/restore.sh` restores. Schedule the dump. |
| **Retention** | set per-org in `/app` → compliance, or `EIDOLON_*`; old events are pruned |
| **Air-gapped** | `docker pull` the image on a connected host, `docker save`/`load` onto the isolated one; everything else is self-contained |

### Key environment variables

| Var | Default | Purpose |
|---|---|---|
| `EIDOLON_ADMIN_TOKEN` | (unset → OPEN, warns) | operator control plane; **set before exposing** |
| `EIDOLON_AUDIT_TOKEN` | (unset) | read-only forensic operator role |
| `EIDOLON_SAGE_BACKEND` | `memory` (image); `postgres` (compose) | attestation ledger substrate |
| `EIDOLON_DATABASE_URL` | SQLite in `/data` (image); Postgres (compose) | operational + ledger store |
| `EIDOLON_PUBLIC_URL` | (unset) | base URL used in connect snippets + notifications |
| `EIDOLON_SESSION_COOKIE_SECURE` | `false` | set `true` behind HTTPS |
| `EIDOLON_ANTHROPIC_API_KEY` | (unset) | only for Claude-voiced drafts/escalations; judgment never uses it |

Full list: [`.env.example`](../.env.example).

---

## The honest boundary

EIDOLON governs, attests, and DLP-taints every call that flows through it. The
airtight "no ungoverned action" guarantee also needs the **workstation/network
locked** so agents can only reach tools through EIDOLON — that egress boundary is
yours to enforce (endpoint policy / network egress rules). EIDOLON gives you the
control point, the evidence, and the kill switch.
