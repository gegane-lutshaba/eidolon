"""Declarative gateway config → a wired :class:`GovernanceEngine`.

An operator declares which profile governs the tools, the authority the gateway
holds (a delegation minted from the principal key), and the per-tool policy map.
``build_engine`` assembles the full KAIROS gate over an in-memory or live SAGE
port and returns a ready engine.

For a real deployment the delegation would be minted offline and the principal
key kept elsewhere; the gateway just holds the (attenuated) credential. This
builder mints it from the principal key for convenience.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from eidolon.basanos import Basanos, KairosTwinAdapter
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.config import Settings
from eidolon.ethos.facade import Ethos
from eidolon.ethos.judgment.grounding import HashingEmbedder
from eidolon.ethos.style import StyleEngine
from eidolon.gateway.engine import GovernanceEngine
from eidolon.gateway.mapping import ToolPolicy, ToolPolicyMap
from eidolon.gateway.purpose import PurposeTracker
from eidolon.gateway.taint import TaintTracker
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import BudgetLedger
from eidolon.profile import ProfileLoader
from eidolon.profile.schema import AutonomyLevel
from eidolon.sage import get_sage
from eidolon.sage.port import SagePort, Scope
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window


class GatewayConfig(BaseModel):
    """Declarative configuration for the governing gateway."""

    profile_id: str = "general-continuity"
    # The principal's Ed25519 signing key (hex). Mints the session delegation.
    principal_signing_key: str
    issued_to: str | None = None  # agent pubkey; generated if omitted
    scope: dict[str, list[str]] = Field(default_factory=dict)
    permitted_classes: list[str] | None = None  # default: all profile classes
    exclusions: list[str] | None = None  # default: profile exclusion types
    max_autonomy: AutonomyLevel = "autonomous"
    budget: dict[str, int] = Field(default_factory=lambda: {"scope_expansion": 0})
    tool_policies: list[ToolPolicy] = Field(default_factory=list)
    default_class: str | None = None
    # Data-flow taint tracking (blocks exfiltration of sensitive read outputs
    # through egress tools). Active only if the profile excludes data-exfiltration.
    enable_taint: bool = True
    # Purpose-limitation tracking (blocks data collected for one purpose from
    # being used by a tool serving another). Active if the profile excludes it.
    enable_purpose: bool = True
    # Optional grounding for ETHOS fidelity (in production this comes from capture).
    seed_memories: list[str] = Field(default_factory=list)


def build_engine(
    config: GatewayConfig,
    *,
    sage: SagePort | None = None,
    style: StyleEngine | None = None,
    settings: Settings | None = None,
) -> GovernanceEngine:
    settings = settings or Settings()
    sage = sage if sage is not None else get_sage()
    profile = ProfileLoader().load(config.profile_id)

    principal_pub = crypto.public_key_from_private(config.principal_signing_key)
    issued_to = config.issued_to or crypto.generate_keypair().public_key_hex

    for content in config.seed_memories:
        sage.observe(principal_pub, content, "memory", "gateway.policy")

    themis = Themis()
    ethos = Ethos(sage, style=style, profile=profile, embedder=HashingEmbedder())
    kairos = Kairos(themis=themis, ethos=ethos, basanos=Basanos(), horkos=Horkos(sage),
                    sage=sage, profile=profile, settings=settings, budget=BudgetLedger())

    budget = dict(config.budget)
    budget.setdefault("scope_expansion", 0)
    root = themis.mint(config.principal_signing_key, MintParams(
        principal_id=principal_pub,
        issued_to=issued_to,
        scope=config.scope,
        exclusions=config.exclusions if config.exclusions is not None else list(profile.mandate_schema.exclusion_types),
        permitted_classes=config.permitted_classes or list(profile.class_names()),
        escalation_required=list(profile.mandate_schema.escalation_required),
        window=Window(),
        blast_radius_budget=budget,
        max_autonomy=config.max_autonomy,
        revocation=Revocation(dead_mans_switch=True),
        nonce="gateway",
    ))

    certs = [
        Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=12,
                    ceiling=profile.default_ceiling(c))
        for c in profile.class_names()
    ]
    # If the profile is integrity-gated by construction, earn the certificate.
    icert = None
    if profile.requires_integrity_certification:
        twin_ut = KairosTwinAdapter(kairos, sage, principal_pub, [root], certs)
        icert = Basanos().certify_integrity(Basanos().integrity_suite(twin_ut, profile))

    policy_map = ToolPolicyMap(
        profile, config.tool_policies,
        default_scope=Scope(selectors=config.scope), default_class=config.default_class,
    )
    # Data-flow layer: on by default when the profile declares data-exfiltration
    # as an excludable boundary (the gateway derives it dynamically).
    excl = profile.mandate_schema.exclusion_types
    taint = TaintTracker() if (config.enable_taint and "data-exfiltration" in excl) else None
    purpose = PurposeTracker() if (config.enable_purpose and "purpose-limitation" in excl) else None
    return GovernanceEngine(
        kairos=kairos, policy_map=policy_map, chain=[root], principal_id=principal_pub,
        certificates=certs, integrity_certificate=icert, taint=taint, purpose=purpose,
    )
