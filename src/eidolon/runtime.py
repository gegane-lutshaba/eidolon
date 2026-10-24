"""Composition root — wires the core components into a twin runtime.

Keeps the assembly of ETHOS/THEMIS/KAIROS/HORKOS/BASANOS in one place so the API
(and tests) construct a fully-wired gate the same way. The SAGE port is chosen
by config (in-memory fake vs live SDK).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from eidolon.basanos import Basanos, Certificate, CertificateIssuer
from eidolon.config import Settings, get_settings
from eidolon.ethos.facade import Ethos
from eidolon.ethos.style import ClaudeStyleEngine
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger
from eidolon.profile import DomainProfile, ProfileLoader
from eidolon.sage import get_sage
from eidolon.sage.port import SagePort
from eidolon.themis import Themis


@dataclass
class Runtime:
    settings: Settings
    sage: SagePort
    profile: DomainProfile
    themis: Themis
    ethos: Ethos
    basanos: Basanos
    horkos: Horkos
    kairos: Kairos
    budget: BudgetLedger
    # Certificates this server issued, by principal -> action class. The API
    # resolves with these (plus caller-presented ones that verify), never with
    # bare caller assertions.
    issuer: CertificateIssuer = field(default_factory=CertificateIssuer)
    issued: dict[str, dict[str, Certificate]] = field(default_factory=dict)

    def certificates_for(self, principal_id: str, presented: list[Certificate] | None = None
                         ) -> tuple[list[Certificate], list[str]]:
        """Effective certificates for a principal: server-issued ones, overlaid
        with caller-presented certificates that carry a valid issuer signature.
        Returns (certificates, rejected classes)."""
        accepted, rejected = self.issuer.accept(list(presented or []), principal_id)
        merged = dict(self.issued.get(principal_id, {}))
        merged.update({c.action_class: c for c in accepted})
        return list(merged.values()), rejected


def build_runtime(
    *,
    settings: Settings | None = None,
    profile_id: str = "general-continuity",
    sage: SagePort | None = None,
) -> Runtime:
    settings = settings or get_settings()
    sage = sage or get_sage()
    profile = ProfileLoader().load(profile_id)

    # On the postgres backend, revocations + heartbeats persist in the
    # operational store: a restart never resurrects revoked authority.
    window = settings.budget_window_seconds
    if settings.sage_backend == "postgres":
        from eidolon.kairos.types import PostgresBudgetLedger
        from eidolon.themis.revocation_store import PostgresRevocationStore

        themis = Themis(
            store=PostgresRevocationStore(settings.heartbeat_ttl_seconds),
            trusted_principals=settings.trusted_principal_ids(),
        )
        budget: BudgetLedger = PostgresBudgetLedger(window)
    elif settings.state_path:
        # No Postgres, but a durable state file: revocations, heartbeats and
        # budgets survive restarts and are shared by every process on the box.
        from eidolon.common.state_db import StateDB
        from eidolon.kairos.types import SqliteBudgetLedger
        from eidolon.themis.revocation_store import SqliteRevocationStore

        db = StateDB(settings.state_path)
        themis = Themis(
            store=SqliteRevocationStore(db, settings.heartbeat_ttl_seconds),
            trusted_principals=settings.trusted_principal_ids(),
        )
        budget = SqliteBudgetLedger(db, window)
    else:
        themis = Themis(
            heartbeat_ttl_seconds=settings.heartbeat_ttl_seconds,
            trusted_principals=settings.trusted_principal_ids(),
        )
        budget = BudgetLedger(window)
    style = ClaudeStyleEngine(settings) if settings.style_enabled else None
    ethos = Ethos(sage, style=style, profile=profile)
    basanos = Basanos()
    horkos = Horkos(sage)
    kairos = Kairos(
        themis=themis,
        ethos=ethos,
        basanos=basanos,
        horkos=horkos,
        sage=sage,
        profile=profile,
        settings=settings,
        budget=budget,
    )
    return Runtime(
        settings=settings,
        sage=sage,
        profile=profile,
        themis=themis,
        ethos=ethos,
        basanos=basanos,
        horkos=horkos,
        kairos=kairos,
        budget=budget,
        issuer=CertificateIssuer(settings.certificate_key),
    )
