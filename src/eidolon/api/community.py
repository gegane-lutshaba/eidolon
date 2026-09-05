"""Community surfaces: contact/collaborate leads + VERSUS meta (leaderboard,
achievements). Small, honest aggregates over the operational store.
"""

from __future__ import annotations

import secrets

_INTERESTS = {"collaborate", "use", "invest", "hire", "other"}


def save_lead(sf, name: str, email: str, handle: str, interest: str, message: str) -> dict:
    from eidolon.data.models import ContactLeadRow

    name, email, handle = name.strip()[:120], email.strip()[:200], handle.strip()[:80]
    message = message.strip()[:4000]
    interest = interest if interest in _INTERESTS else "other"
    if not (email or handle):
        raise ValueError("an email or a handle is required so we can reach you")
    if not message:
        raise ValueError("tell us a little about what you have in mind")
    lead = ContactLeadRow(id=f"lead-{secrets.token_urlsafe(9)}", name=name, email=email,
                          handle=handle, interest=interest, message=message)
    with sf() as s:
        s.add(lead)
        s.commit()
        return {"id": lead.id, "interest": lead.interest}


def list_leads(sf, limit: int = 500) -> list[dict]:
    from sqlalchemy import select

    from eidolon.data.models import ContactLeadRow

    with sf() as s:
        rows = s.execute(select(ContactLeadRow)
                         .order_by(ContactLeadRow.created_at.desc()).limit(limit)).scalars().all()
    return [{"id": r.id, "name": r.name, "email": r.email, "handle": r.handle,
             "interest": r.interest, "message": r.message,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


def record_versus(sf, scenario_id: str, authority: str, flawless: bool) -> None:
    from eidolon.data.models import VersusRunRow

    with sf() as s:
        s.add(VersusRunRow(scenario_id=scenario_id, authority=authority, flawless=flawless))
        s.commit()


def versus_stats(sf) -> dict:
    """Honest aggregates for the landing + leaderboard."""
    from sqlalchemy import func, select

    from eidolon.data.models import VersusRunRow

    with sf() as s:
        total = s.execute(select(func.count()).select_from(VersusRunRow)).scalar() or 0
        flawless = s.execute(select(func.count()).select_from(VersusRunRow)
                             .where(VersusRunRow.flawless.is_(True))).scalar() or 0
        rows = s.execute(
            select(VersusRunRow.scenario_id, func.count().label("n"))
            .group_by(VersusRunRow.scenario_id).order_by(func.count().desc())
        ).all()
    return {
        "battles_fought": int(total),
        "flawless_victories": int(flawless),
        "leaderboard": [{"scenario_id": sid, "runs": int(n)} for sid, n in rows],
    }
