"""Runtime configuration (pydantic-settings).

All knobs are environment-driven so the same code runs in the fast (in-memory)
test lane and against a live Dockerized SAGE node. See ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EIDOLON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- SAGE substrate ---------------------------------------------------
    # backend: "memory" for the fast lane, "postgres" for a persistent single
    # box (docker compose), "sage" to bind the live BFT-consensus SDK.
    sage_backend: Literal["memory", "postgres", "sage"] = "memory"
    sage_base_url: str = "http://localhost:8080"
    sage_agent_key_path: str = "~/.sage/agent.key"
    sage_ca_cert: str | None = None
    # Domain used to persist HORKOS attestations on the consensus ledger.
    sage_attestation_domain: str = "attestations"
    # Postgres port: max most-recent memories per principal loaded before ranking.
    sage_pg_recall_prefetch: int = 5000

    # --- ETHOS style engine (Claude) -------------------------------------
    anthropic_api_key: str | None = None
    style_model: str = "claude-sonnet-4-6"
    style_max_tokens: int = 1024
    # When true the style engine must never be constructed by judgment code.
    style_enabled: bool = True

    # --- Operational store (Postgres + pgvector) -------------------------
    database_url: str = "postgresql+psycopg://eidolon:eidolon@localhost:5432/eidolon"

    # --- KAIROS global autonomy dial (PRD §6.4 step 3) -------------------
    # The org-wide ceiling; the effective level is min(cred, basanos, dial).
    autonomy_dial: Literal["observe", "draft", "notify", "autonomous"] = "autonomous"

    # --- THEMIS dead-man's-switch ----------------------------------------
    heartbeat_ttl_seconds: int = Field(default=3600, ge=1)

    # --- BASANOS integrity gating (v2) -----------------------------------
    # When true, an autonomy level above 'draft' also requires a passing
    # integrity certificate (adversarial robustness), not just fidelity.
    require_integrity_certification: bool = False

    # --- Service ----------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # --- Operator auth (single tenant, two roles) ------------------------
    # Two secrets grant two roles, accepted as `Authorization: Bearer <token>`
    # or a login cookie:
    #   EIDOLON_ADMIN_TOKEN -> "admin"   : full control plane (mint/revoke, approve…)
    #   EIDOLON_AUDIT_TOKEN -> "auditor" : read-only forensic surface (/audit, /replay)
    # Fail-closed: with either set, unauthenticated/insufficient access is denied.
    # With NEITHER set the platform runs OPEN (localhost dev only) and warns once.
    admin_token: str | None = None
    audit_token: str | None = None
    # Mark the session cookie Secure (HTTPS only). Enable behind a TLS proxy.
    session_cookie_secure: bool = False
    # Optional comma-separated Host allow-list (adds TrustedHostMiddleware).
    trusted_hosts: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
