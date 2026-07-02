"""Composition root — wires the core components into a twin runtime.

Keeps the assembly of ETHOS/THEMIS/KAIROS/HORKOS/BASANOS in one place so the API
(and tests) construct a fully-wired gate the same way. The SAGE port is chosen
by config (in-memory fake vs live SDK).
"""

from __future__ import annotations

from dataclasses import dataclass

from eidolon.basanos import Basanos
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


def build_runtime(
    *,
    settings: Settings | None = None,
    profile_id: str = "general-continuity",
    sage: SagePort | None = None,
) -> Runtime:
    settings = settings or get_settings()
    sage = sage or get_sage()
    profile = ProfileLoader().load(profile_id)

    themis = Themis(heartbeat_ttl_seconds=settings.heartbeat_ttl_seconds)
    style = ClaudeStyleEngine(settings) if settings.style_enabled else None
    ethos = Ethos(sage, style=style, profile=profile)
    basanos = Basanos()
    horkos = Horkos(sage)
    budget = BudgetLedger()
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
    )
