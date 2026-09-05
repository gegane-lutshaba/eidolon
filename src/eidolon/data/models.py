"""SQLAlchemy models (PRD §7).

Ownership rule (LOCKED): ``Principal`` is the tenant. ``ContinuityGrant`` is the
ONLY mechanism by which an organization accesses a twin — scoped, time-boxed,
and revocable by the principal or an authorized independent revoker. No
org-owned twins in v1.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eidolon.data.db import Base


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class PrincipalRow(Base):
    __tablename__ = "principals"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # ed25519 pubkey (hex)
    display_name: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    twins: Mapped[list[TwinRow]] = relationship(back_populates="principal")


class TwinRow(Base):
    __tablename__ = "twins"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # twin agent pubkey
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    ethos_version: Mapped[str] = mapped_column(String, default="")
    profile_id: Mapped[str] = mapped_column(String, default="")
    profile_version: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    principal: Mapped[PrincipalRow] = relationship(back_populates="twins")


class DomainProfileRow(Base):
    __tablename__ = "domain_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, primary_key=True)
    manifest: Mapped[dict] = mapped_column(JSON)  # immutable once written


class DelegationRow(Base):
    __tablename__ = "delegations"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # content hash of body
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    issued_to: Mapped[str] = mapped_column(String)
    parent: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[dict] = mapped_column(JSON)  # DelegationBody
    signature: Mapped[str] = mapped_column(Text)
    revoked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ConsentGrantRow(Base):
    __tablename__ = "consent_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    source: Mapped[str] = mapped_column(String)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    not_before: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    not_after: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContinuityGrantRow(Base):
    __tablename__ = "continuity_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"))
    org_id: Mapped[str] = mapped_column(String)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    not_before: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    not_after: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Revocable by the principal or an authorized independent revoker.
    revoker_ids: Mapped[list] = mapped_column(JSON, default=list)
    revoked: Mapped[bool] = mapped_column(default=False)


# -- platform runtime state (survives restarts on the postgres backend) ---
class RevocationRow(Base):
    """An explicitly revoked delegation id. Presence = revoked (irreversible)."""

    __tablename__ = "revocations"

    delegation_id: Mapped[str] = mapped_column(String, primary_key=True)
    revoked_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class HeartbeatRow(Base):
    """Last dead-man's-switch heartbeat per principal."""

    __tablename__ = "heartbeats"

    principal_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_beat: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EscalationRow(Base):
    """A pending/settled approval-inbox item (serialized EscalationRequest)."""

    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True, default="pending")
    payload: Mapped[dict] = mapped_column(JSON)  # EscalationRequest (mode="json")
    # Execution context so an approval can re-execute the exact action:
    # {"chain": [Delegation...], "certificates": [Certificate...]}.
    exec_context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UserRow(Base):
    """A platform account (self-hosted multi-user)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # random urlsafe id
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    # "scrypt$<salt_hex>$<hash_hex>" (stdlib scrypt; no plaintext ever stored)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UserSessionRow(Base):
    """A browser session for a user (revocable, expiring)."""

    __tablename__ = "user_sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)  # random urlsafe
    user_id: Mapped[str] = mapped_column(String, index=True)
    expires_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True))


class OrgRow(Base):
    """A team. Every user gets a personal org on signup; agents belong to an org."""

    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "org-<rand>"
    name: Mapped[str] = mapped_column(String, default="")
    personal: Mapped[bool] = mapped_column(default=False)  # the owner's auto-created team
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # declared policy
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OrgMemberRow(Base):
    """Membership + role. Roles rank auditor < member < admin < owner."""

    __tablename__ = "org_members"

    org_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String, default="member")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OrgInviteRow(Base):
    """A one-shot-ish invite code granting a role in an org."""

    __tablename__ = "org_invites"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default="member")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentRow(Base):
    """A registered agent: its gateway identity + reporting credential.

    The agent's ``id`` doubles as the ``gateway_id`` its gateway reports under,
    so ownership of gateways/events resolves through this table. Owned by an
    ``org``; ``user_id`` records the creator.
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "agt-<rand>"
    user_id: Mapped[str] = mapped_column(String, index=True)  # creator
    org_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String)
    preset: Mapped[str] = mapped_column(String, default="reader")  # authority preset
    gateway_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PasswordResetRow(Base):
    """A one-shot password-reset token (expiring)."""

    __tablename__ = "password_resets"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    expires_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True))


class AgentKeyRow(Base):
    """An agent's principal keypair, minted at enrollment (custodial v1).

    Kept in its own table (not a column on agents) so create_all provisions it
    without migrations. The signing key lets the wizard emit a complete,
    paste-and-go gateway.yaml; self-custody users can replace it in the yaml
    and delete the row.
    """

    __tablename__ = "agent_keys"

    agent_id: Mapped[str] = mapped_column(String, primary_key=True)
    public_hex: Mapped[str] = mapped_column(String)
    signing_hex: Mapped[str] = mapped_column(String)


class ContactLeadRow(Base):
    """A collaboration/contact submission (the JOIN THE CO-OP funnel)."""

    __tablename__ = "contact_leads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    handle: Mapped[str] = mapped_column(String, default="")
    interest: Mapped[str] = mapped_column(String, default="")  # collaborate | use | invest | other
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CertificationRow(Base):
    """An EIDOLON certification: an agent config run against the VERSUS attack
    library. Public certificates back a shareable badge + scorecard page."""

    __tablename__ = "certifications"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "cert-<rand>"
    agent_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String, index=True, default="")
    subject: Mapped[str] = mapped_column(String, default="")  # agent display name
    kind: Mapped[str] = mapped_column(String, default="coding")
    authority: Mapped[str] = mapped_column(String, default="builder")
    rank: Mapped[str] = mapped_column(String, default="DRAFTER")
    total: Mapped[int] = mapped_column(Integer, default=0)
    contained: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="CERTIFIED")  # CERTIFIED | PARTIAL
    results: Mapped[dict] = mapped_column(JSON, default=dict)  # per-scenario scorecard
    public: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class VersusRunRow(Base):
    """One VERSUS battle (aggregate meta: leaderboard + achievements)."""

    __tablename__ = "versus_runs"

    seq: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    scenario_id: Mapped[str] = mapped_column(String, index=True)
    authority: Mapped[str] = mapped_column(String, default="")
    flawless: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GatewayRow(Base):
    """A connected gateway (one governed agent connection) + its kill state."""

    __tablename__ = "gateways"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # operator-chosen gateway id
    agent: Mapped[str] = mapped_column(String, default="")  # display name, e.g. "claude-code"
    killed: Mapped[bool] = mapped_column(default=False)
    last_seen: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    events: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), default=0)


class GatewayEventRow(Base):
    """One governed decision reported by a gateway (mission-control feed)."""

    __tablename__ = "gateway_events"

    seq: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    gateway_id: Mapped[str] = mapped_column(String, index=True)
    agent: Mapped[str] = mapped_column(String, default="")
    tool: Mapped[str] = mapped_column(String)
    action_class: Mapped[str] = mapped_column(String, default="")
    level: Mapped[str] = mapped_column(String, index=True)
    allowed: Mapped[bool] = mapped_column(default=False)
    attestation_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")  # redacted arg summary
    rationale: Mapped[str] = mapped_column(Text, default="")
    ts: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
