# EIDOLON on-prem image: the FastAPI service (dashboard, gate, gateway API).
# Two ways to run it (see docs/on-prem.md):
#   Trial   — docker run -p 8000:8000 ghcr.io/gegane-lutshaba/eidolon
#             (SQLite operational store in /data + in-memory ledger; ephemeral)
#   Prod    — docker compose -f docker-compose.deploy.yml up -d
#             (Postgres-backed SAGE port; persistent, hash-chained ledger)
# Built with uv for reproducible installs; runs as a non-root user.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    # Trial-friendly defaults so a bare `docker run` just works. The production
    # compose overrides these (EIDOLON_SAGE_BACKEND=postgres + a Postgres URL).
    EIDOLON_SAGE_BACKEND=memory \
    EIDOLON_DATABASE_URL=sqlite:////data/eidolon.db \
    EIDOLON_API_HOST=0.0.0.0 \
    EIDOLON_API_PORT=8000

LABEL org.opencontainers.image.title="EIDOLON" \
      org.opencontainers.image.description="The cryptographic authority layer for AI agents — seen, bounded, revocable." \
      org.opencontainers.image.source="https://github.com/gegane-lutshaba/eidolon" \
      org.opencontainers.image.licenses="Apache-2.0"

# uv from its official distroless image (pinned major).
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /uvx /bin/

WORKDIR /app

# Project metadata + sources are needed to build the local package.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY docs/whitepaper.md ./docs/whitepaper.md

# Resolve and install into /app/.venv. No dev deps; mcp powers the hosted
# /mcp gateway tier (managed access).
RUN uv sync --frozen --no-dev --extra mcp

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as a non-root user; /data holds the SQLite store in trial mode (volume).
RUN useradd --system --uid 10001 --home-dir /app eidolon \
    && mkdir -p /data \
    && chown -R eidolon:eidolon /app /data
USER eidolon
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)" || exit 1
ENTRYPOINT ["/entrypoint.sh"]
