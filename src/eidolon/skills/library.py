"""Skill library — principal-scoped procedural memory on SAGE (PRD §2.2 v2).

Skills persist as SAGE observations of type ``skill`` (canonical JSON content),
so they inherit the substrate's principal isolation and provenance: one
principal's skills are never recalled for another. Following Hermes, skills are
loaded *when relevant* — retrieval is a scoped semantic recall over the query.
"""

from __future__ import annotations

from eidolon.common.canonical import canonical_json
from eidolon.sage.port import SagePort, Scope
from eidolon.skills.types import Skill

_SKILL_TYPE = "skill"
_PROVENANCE = "eidolon.skills"


class SkillLibrary:
    def __init__(self, sage: SagePort) -> None:
        self._sage = sage

    def save(self, skill: Skill) -> str:
        """Persist a skill for its principal. Returns the SAGE mem_id."""
        return self._sage.observe(
            principal_id=skill.principal_id,
            content=canonical_json(skill),
            type=_SKILL_TYPE,
            provenance=_PROVENANCE,
        )

    def load(self, principal_id: str, query: str, k: int = 5) -> list[Skill]:
        """Recall the most relevant skills for a principal + task query.

        Skills share the principal's recall space with observations, so we
        over-fetch and filter by type before truncating to ``k`` — otherwise a
        flood of relevant observations could crowd the skills out of top-k.
        """
        over_fetch = max(k * 5, 40)
        memories = self._sage.recall(principal_id, Scope(), query, k=over_fetch)
        out: list[Skill] = []
        for m in memories:
            if m.type != _SKILL_TYPE:
                continue
            skill = _parse(m.content)
            if skill is not None:
                out.append(skill)
            if len(out) >= k:
                break
        return out

    def get(self, principal_id: str, skill_id: str) -> Skill | None:
        for skill in self.load(principal_id, skill_id, k=100):
            if skill.id == skill_id:
                return skill
        return None


def _parse(content: str) -> Skill | None:
    try:
        return Skill.model_validate_json(content)
    except Exception:
        return None
