"""Self-generated procedural skills (PRD §2.2, §12 — v2, Hermes-style).

A skill is a *learned plan*: an ordered, parameterized sequence of capability
classes the twin figured out for a recurring task. Skills are **subordinate to
ETHOS and THEMIS** — replaying a skill re-resolves every step through KAIROS
(authority + fidelity + attest-then-act). A skill therefore can never bypass the
gate, widen authority, or execute an unattested action; it only *proposes* the
steps. Skills are principal-owned and stored on the SAGE substrate.
"""

from eidolon.skills.executor import SkillExecutor
from eidolon.skills.library import SkillLibrary
from eidolon.skills.synthesis import should_synthesize, synthesize
from eidolon.skills.types import Skill, SkillRun, SkillStep, StepOutcome

__all__ = [
    "Skill",
    "SkillStep",
    "SkillRun",
    "StepOutcome",
    "synthesize",
    "should_synthesize",
    "SkillLibrary",
    "SkillExecutor",
]
