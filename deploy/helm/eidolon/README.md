# EIDOLON Helm chart

Deploy EIDOLON on Kubernetes: the app + (optionally) a bundled Postgres for the
persistent, hash-chained attestation ledger.

## Install

```bash
# From the published OCI chart (no checkout needed):
helm install eidolon oci://ghcr.io/gegane-lutshaba/charts/eidolon --version 0.1.0 \
  --namespace eidolon --create-namespace \
  --set secrets.adminToken="$(openssl rand -hex 32)" \
  --set secrets.dbPassword="$(openssl rand -hex 24)" \
  --set config.publicUrl=https://eidolon.yourco.com
```

```bash
# …or from a checkout:
helm install eidolon ./deploy/helm/eidolon \
  --namespace eidolon --create-namespace \
  --set secrets.adminToken="$(openssl rand -hex 32)" \
  --set secrets.dbPassword="$(openssl rand -hex 24)" \
  --set config.publicUrl=https://eidolon.yourco.com \
  --set ingress.enabled=true --set ingress.host=eidolon.yourco.com \
  --set ingress.tls.enabled=true --set ingress.tls.secretName=eidolon-tls
```

Then point every agent at `EIDOLON_URL=https://eidolon.yourco.com` (the Claude
Code hook and `/mcp` both take a URL).

## Common options

| Value | Default | Notes |
|---|---|---|
| `image.tag` | `latest` | pin to a release for prod |
| `secrets.adminToken` | `""` | **set it** — empty runs OPEN |
| `secrets.existingSecret` | `""` | use your own Secret instead of chart-managed (same keys) |
| `postgres.enabled` | `true` | bundled pgvector StatefulSet + PVC |
| `postgres.storage` | `10Gi` | ledger volume size |
| `externalDatabase.url` | `""` | set (and `postgres.enabled=false`) to use managed Postgres |
| `config.oidc.issuer` | `""` | set + `secrets.oidcClientSecret` to enable SSO |
| `config.oidc.orgName` | `""` | land all SSO users in one shared team |
| `ingress.*` | disabled | bring your own controller + cert-manager |

Full list: [`values.yaml`](values.yaml).

## Bring your own database

```bash
helm install eidolon ./deploy/helm/eidolon \
  --set postgres.enabled=false \
  --set externalDatabase.url='postgresql+psycopg://user:pass@pg.internal:5432/eidolon' \
  --set secrets.adminToken="$(openssl rand -hex 32)"
```

## Secrets via an existing Secret

Create a Secret with keys `EIDOLON_ADMIN_TOKEN`, `EIDOLON_AUDIT_TOKEN`,
`EIDOLON_DB_PASSWORD`, `EIDOLON_OIDC_CLIENT_SECRET`, then:

```bash
helm install eidolon ./deploy/helm/eidolon --set secrets.existingSecret=my-eidolon-secret
```

The app image runs as a non-root user (uid 10001) with dropped capabilities.
