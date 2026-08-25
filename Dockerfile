# EIDOLON single-box image: the FastAPI service (dashboard, gate, gateway API)
# over a Postgres-backed SAGE port. Built with uv for reproducible installs.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# uv from its official distroless image (pinned major).
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /uvx /bin/

WORKDIR /app

# Project metadata + sources are needed to build the local package.
COPY pyproject.toml README.md ./
COPY src ./src

# Resolve and install into /app/.venv. No dev deps in the image.
RUN uv sync --no-dev

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
