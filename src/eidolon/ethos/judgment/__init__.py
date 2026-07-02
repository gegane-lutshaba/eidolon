"""ETHOS judgment engine — auditable, LLM-free (PRD §6.2).

SECURITY BOUNDARY: nothing in this package may import ``eidolon.ethos.style``.
The judgment engine is the only producer of ``decision``/``confidence`` and must
be fully inspectable. An automated import-graph test enforces this.
"""

from eidolon.ethos.judgment.engine import JudgmentEngine

__all__ = ["JudgmentEngine"]
