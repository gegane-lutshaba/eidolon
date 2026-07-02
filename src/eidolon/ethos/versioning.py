"""ETHOS versioning — content-addressed, diff-able snapshots (PRD §6.2).

``snapshot()`` captures the judgment policy configuration (the auditable part)
plus the style profile identity, and derives a stable ``ethos_version`` hash
from the canonical bytes. Two versions are diff-able so an auditor (or the v2
aspirational-self layer) can see exactly what changed between them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eidolon.common.canonical import content_hash


class EthosSnapshot(BaseModel):
    """A versioned, diff-able capture of an ETHOS configuration."""

    # Auditable judgment-policy parameters (the load-bearing part).
    judgment_policy: dict[str, Any] = Field(default_factory=dict)
    # Style identity only — never policy. Records which voice model is bound.
    style_profile: dict[str, Any] = Field(default_factory=dict)
    profile_id: str | None = None
    profile_version: str | None = None

    @property
    def version(self) -> str:
        # Version derives ONLY from content that affects behavior. The style
        # model id is included for provenance but note: changing it must not
        # change any decision (proved by the isolation test).
        return "ethos-" + content_hash(
            {
                "judgment_policy": self.judgment_policy,
                "style_profile": self.style_profile,
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
            }
        )[:16]


def snapshot(
    judgment_policy: dict[str, Any],
    style_profile: dict[str, Any] | None = None,
    *,
    profile_id: str | None = None,
    profile_version: str | None = None,
) -> EthosSnapshot:
    return EthosSnapshot(
        judgment_policy=judgment_policy,
        style_profile=style_profile or {},
        profile_id=profile_id,
        profile_version=profile_version,
    )


def diff_snapshots(a: EthosSnapshot, b: EthosSnapshot) -> dict[str, Any]:
    """Structured diff between two snapshots (added/removed/changed keys)."""
    da, db = a.model_dump(), b.model_dump()
    diff: dict[str, Any] = {
        "version_from": a.version,
        "version_to": b.version,
        "changed": {},
    }
    for key in sorted(set(da) | set(db)):
        if da.get(key) != db.get(key):
            diff["changed"][key] = {"from": da.get(key), "to": db.get(key)}
    return diff
