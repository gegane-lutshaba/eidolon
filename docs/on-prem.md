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

## SSO (staff sign-in via your IdP)

Let employees sign in with the company IdP instead of a separate password. Set
three env vars (Google, Okta, Azure AD, Authentik — anything OIDC):

```bash
EIDOLON_OIDC_ISSUER=https://<tenant>.okta.com
EIDOLON_OIDC_CLIENT_ID=...
EIDOLON_OIDC_CLIENT_SECRET=...
# optional:
EIDOLON_OIDC_ALLOWED_DOMAINS=yourco.com      # only these email domains
EIDOLON_OIDC_ORG_NAME="YourCo"               # land everyone in one shared team
EIDOLON_OIDC_BUTTON_LABEL="Okta"
```

Register **`<EIDOLON_PUBLIC_URL>/auth/sso/callback`** as the IdP redirect URI.
A "Sign in with …" button then appears at `/signup`; first login provisions the
user (no password), drops them into `EIDOLON_OIDC_ORG_NAME` if set, and opens a
session. With `EIDOLON_OIDC_ORG_NAME`, the first user is the org owner and the
rest join as members — so IT sees the whole company's agents in one team.

## Kubernetes (Helm)

For k8s shops, a chart lives at [`deploy/helm/eidolon`](../deploy/helm/eidolon)
— the app plus an optional bundled Postgres (persistent ledger), or bring your
own database.

```bash
# Published OCI chart — no checkout needed:
helm install eidolon oci://ghcr.io/gegane-lutshaba/charts/eidolon --version 0.1.0 \
  --namespace eidolon --create-namespace \
  --set secrets.adminToken="$(openssl rand -hex 32)" \
  --set secrets.dbPassword="$(openssl rand -hex 24)" \
  --set config.publicUrl=https://eidolon.yourco.com \
  --set ingress.enabled=true --set ingress.host=eidolon.yourco.com
```

See the [chart README](../deploy/helm/eidolon/README.md) for external-database,
existing-secret, and SSO options.

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
