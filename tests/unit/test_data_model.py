"""Operational store smoke (PRD §7) — create_all + basic ownership wiring."""

from __future__ import annotations

from eidolon.data import init_db
from eidolon.data.db import get_sessionmaker
from eidolon.data.models import ContinuityGrantRow, PrincipalRow, TwinRow

SQLITE = "sqlite://"  # shared in-memory for this test process


def test_principal_owns_twin_and_continuity_grant() -> None:
    init_db(SQLITE)
    Session_ = get_sessionmaker(SQLITE)
    with Session_() as s:  # type: Session
        s.add(PrincipalRow(id="pub-A", display_name="Ada"))
        s.add(TwinRow(id="twin-A", principal_id="pub-A", profile_id="general-continuity"))
        s.add(
            ContinuityGrantRow(
                id="cg-1", principal_id="pub-A", org_id="acme",
                scope={"project": ["atlas"]}, revoker_ids=["pub-A"],
            )
        )
        s.commit()

    with Session_() as s:
        principal = s.get(PrincipalRow, "pub-A")
        assert principal is not None
        assert [t.id for t in principal.twins] == ["twin-A"]
        grant = s.get(ContinuityGrantRow, "cg-1")
        # ContinuityGrant is the only org-access mechanism and is revocable.
        assert grant.org_id == "acme" and grant.revoked is False
