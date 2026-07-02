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
    # backend: "memory" for the fast lane, "sage" to bind the live SDK.
    sage_backend: Literal["memory", "sage"] = "memory"
    sage_base_url: str = "http://localhost:8080"
    sage_agent_key_path: str = "~/.sage/agent.key"
    sage_ca_cert: str | None = None
    # Domain used to persist HORKOS attestations on the consensus ledger.
    sage_attestation_domain: str = "attestations"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
