"""ETHOS style engine — generative voice (PRD §6.2).

Renders register/voice for drafts and escalation messages ONLY. It must never
emit or influence a ``decision``, ``confidence``, or scope determination. It
takes an already-decided outcome and renders prose; it returns ``str``, never a
``Judgment``.
"""

from eidolon.ethos.style.engine import ClaudeStyleEngine, StyleEngine

__all__ = ["StyleEngine", "ClaudeStyleEngine"]
