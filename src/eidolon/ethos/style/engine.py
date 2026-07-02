"""Claude-backed style engine (PRD §6.2, §11).

Wired to Claude (Anthropic SDK, default ``claude-sonnet-4-6``). Two entry points:

    draft(action, context, profile)          -> text     # renders a draft comm
    render_escalation(template, fields)       -> text     # renders an escalation

The engine only ever RENDERS. It receives a decision that was already made by
the judgment engine and produces prose in the principal's voice. It returns
strings; it has no access to and never returns ``Judgment`` objects.

If no API key is configured the engine degrades to deterministic template
rendering so the system still runs — voice fidelity is reduced but no decision
path depends on the LLM.
"""

from __future__ import annotations

from typing import Any, Protocol

from eidolon.config import Settings, get_settings
from eidolon.profile.schema import DomainProfile
from eidolon.types import Action, Context


class StyleEngine(Protocol):
    def draft(self, action: Action, context: Context, profile: DomainProfile) -> str: ...
    def render_escalation(self, template: str, fields: dict[str, Any]) -> str: ...


_SYSTEM_PROMPT = (
    "You are the voice-rendering layer of a digital twin. You are given a "
    "decision that has ALREADY been made by a separate, auditable system. Your "
    "ONLY job is to phrase the message in the principal's professional voice: "
    "clear, warm, concise. You must NOT change, question, or add to the "
    "decision, add new commitments, or invent facts. Render only what you are "
    "given."
)


class ClaudeStyleEngine:
    """Style engine backed by Claude, with a deterministic template fallback."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any | None = None
        if self._settings.anthropic_api_key:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
            except ImportError:
                self._client = None

    # -- public API -------------------------------------------------------
    def draft(self, action: Action, context: Context, profile: DomainProfile) -> str:
        instruction = (
            f"Draft a {action.action_class} on behalf of the principal.\n"
            f"Purpose: {action.description}\n"
            f"Relevant situation: {context.situation or context.query}\n"
            "Return only the message body."
        )
        fallback = (
            f"[DRAFT — {action.action_class}] {action.description}"
            + (f"\n\nContext: {context.situation}" if context.situation else "")
        )
        return self._generate(instruction, fallback)

    def render_escalation(self, template: str, fields: dict[str, Any]) -> str:
        # The template comes from the profile; fields fill its placeholders. The
        # LLM only smooths phrasing — the template already encodes intent.
        base = _safe_format(template, fields)
        instruction = (
            "Rephrase the following escalation note in the principal's voice, "
            "keeping its meaning and urgency exactly:\n\n" + base
        )
        return self._generate(instruction, base)

    # -- internals --------------------------------------------------------
    def _generate(self, instruction: str, fallback: str) -> str:
        if self._client is None:
            return fallback
        try:
            msg = self._client.messages.create(
                model=self._settings.style_model,
                max_tokens=self._settings.style_max_tokens,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": instruction}],
            )
            parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
            return "".join(parts).strip() or fallback
        except Exception:
            # Never let a style failure break a flow; fall back to the template.
            return fallback


def _safe_format(template: str, fields: dict[str, Any]) -> str:
    class _Default(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(_Default(fields))
