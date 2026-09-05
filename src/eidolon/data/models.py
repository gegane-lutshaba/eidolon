"""SQLAlchemy models (PRD §7).

Ownership rule (LOCKED): ``Principal`` is the tenant. ``ContinuityGrant`` is the
ONLY mechanism by which an organization accesses a twin — scoped, time-boxed,
and revocable by the principal or an authorized independent revoker. No
org-owned twins in v1.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
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
