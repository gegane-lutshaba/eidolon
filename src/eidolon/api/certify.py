"""Certification-as-a-service.

Run an agent's config against the whole VERSUS attack library and issue a
public **certificate**: proof that, governed by EIDOLON at its chosen rank, the
agent contains every harmful step of every known attack — and a scorecard of
what the *same* attacks would have done to it ungoverned. Backs a shareable
badge (README-embeddable) and a public scorecard page.

Honest by construction: the "with EIDOLON" column is the real GovernanceEngine
(via `showcase.versus`), and every attack is credited to public research. As
the library grows, re-certification is one click — a certificate names the
corpus size it was issued against.
"""

from __future__ import annotations

import secrets

from eidolon.showcase import versus


def run_certification(sf, *, agent_id: str | None, user_id: str, subject: str,
                      kind: str, authority: str) -> dict:
    """Run the full attack library at `authority`; store + return a certificate."""
    from eidolon.api.accounts import PRESETS
    from eidolon.data.models import CertificationRow

    rank = PRESETS.get(authority, PRESETS["builder"])["rank"]
    results = []
    contained = 0
    for scn in versus.SCENARIOS:
        r = versus.run_versus(scn.id, authority)
        wi, wo = r["with_eidolon"], r["without"]
        ok = wi["verdict"] == "FLAWLESS"
        contained += 1 if ok else 0
        results.append({
            "scenario_id": scn.id, "title": scn.title, "agent_mirror": scn.agent,
            "source": scn.source, "contained": ok,
            "stopped": wi["stopped"], "harmful": wi["harmful"],
            "without_verdict": wo["verdict"],
            "without_damage": wo["damage"],
        })
    total = len(versus.SCENARIOS)
    status = "CERTIFIED" if contained == total and total > 0 else "PARTIAL"
    cert = CertificationRow(
        id=f"cert-{secrets.token_urlsafe(8)}", agent_id=agent_id, user_id=user_id,
        subject=subject or "agent", kind=kind, authority=authority, rank=rank,
        total=total, contained=contained, status=status, results=results, public=True,
    )
    with sf() as s:
        s.add(cert)
        s.commit()
        return _cert_dict(cert)


def get_certification(sf, cert_id: str) -> dict | None:
    from eidolon.data.models import CertificationRow

    with sf() as s:
        c = s.get(CertificationRow, cert_id)
    return _cert_dict(c) if c and c.public else None


def list_certifications(sf, limit: int = 100) -> list[dict]:
    from sqlalchemy import select

    from eidolon.data.models import CertificationRow

    with sf() as s:
        rows = s.execute(
            select(CertificationRow).where(CertificationRow.public.is_(True))
            .order_by(CertificationRow.created_at.desc()).limit(limit)
        ).scalars().all()
    return [_cert_dict(c, brief=True) for c in rows]


def badge_svg(cert: dict) -> str:
    """A shields.io-style embeddable badge."""
    certified = cert["status"] == "CERTIFIED"
    right = f"{cert['contained']}/{cert['total']} contained" if certified else \
            f"{cert['contained']}/{cert['total']} partial"
    color = "#39d98a" if certified else "#f2b84b"
    label, lw, rw = "EIDOLON", 66, 8 * len(right) + 20
    w = lw + rw
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="EIDOLON: {right}">
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
  <stop offset="1" stop-opacity=".1"/></linearGradient>
  <rect rx="3" width="{w}" height="20" fill="#07090f"/>
  <rect rx="3" x="{lw}" width="{rw}" height="20" fill="{color}"/>
  <rect rx="3" width="{w}" height="20" fill="url(#s)"/>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">
    <text x="{lw / 2:.0f}" y="14" fill="#8b7bff" font-weight="bold">{label}</text>
    <text x="{lw + rw / 2:.0f}" y="14" fill="#07090f" font-weight="bold">{right}</text>
  </g>
</svg>"""


def _cert_dict(c, brief: bool = False) -> dict:
    d = {"id": c.id, "subject": c.subject, "kind": c.kind, "authority": c.authority,
         "rank": c.rank, "total": c.total, "contained": c.contained, "status": c.status,
         "created_at": c.created_at.isoformat() if c.created_at else None}
    if not brief:
        d["results"] = c.results
    return d
