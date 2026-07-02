"""ETHOS facade (PRD §6.2 interface).

Composes the two hard-isolated engines behind the §6.2 interface:

    evaluate(action, context, memories, profile) -> Judgment   # judgment engine
    draft(action, context, profile) -> text                    # style engine
    snapshot() -> ethos_version

Composition happens HERE, at the top, never inside the judgment engine. The
judgment engine has no reference to the style engine, so removing the style
engine changes zero decision/confidence outputs (the §6.2 acceptance test).
``draft`` is a thin pass-through to the style engine; a facade constructed with
``style=None`` simply cannot draft, but can still fully evaluate.
"""

from __future__ import annotations

from eidolon.ethos.judgment import JudgmentEngine
from eidolon.ethos.style import StyleEngine
from eidolon.ethos.types import Judgment
from eidolon.ethos.versioning import EthosSnapshot, snapshot
from eidolon.profile.schema import DomainProfile
from eidolon.sage.port import Memory, SagePort
from eidolon.types import Action, Context

# Per-class confidence thresholds default; a profile may override via
# fidelity_rubric.calibration_target as a floor. Below threshold -> ESCALATE.
_DEFAULT_THRESHOLD = 0.7


class Ethos:
    def __init__(
        self,
        sage: SagePort,
        *,
        style: StyleEngine | None = None,
        profile: DomainProfile | None = None,
    ) -> None:
        self._judgment = JudgmentEngine(sage)
        self._style = style
        self._profile = profile

    # -- judgment (auditable) --------------------------------------------
    def evaluate(
        self,
        action: Action,
        context: Context,
        memories: list[Memory] | None,
        profile: DomainProfile,
    ) -> Judgment:
        return self._judgment.evaluate(action, context, memories, profile)

    def confidence_threshold(self, action_class: str, profile: DomainProfile) -> float:
        """Per-class confidence threshold, sourced from the profile (§P1.2.3).

        Decision points named in the fidelity rubric are held to at least the
        profile's calibration target; other classes use the default.
        """
        if action_class in profile.fidelity_rubric.decision_points:
            return max(_DEFAULT_THRESHOLD, profile.fidelity_rubric.calibration_target)
        return _DEFAULT_THRESHOLD

    # -- style (generative, isolated) ------------------------------------
    def draft(self, action: Action, context: Context, profile: DomainProfile) -> str:
        if self._style is None:
            # Deterministic fallback keeps drafting working without a style
            # engine (tests, no API key). Voice fidelity is reduced; no decision
            # depends on this.
            situation = context.situation or context.query
            return f"[DRAFT — {action.action_class}] {action.description}" + (
                f"\n\nContext: {situation}" if situation else ""
            )
        return self._style.draft(action, context, profile)

    def render_escalation(self, template: str, fields: dict) -> str:
        if self._style is None:
            # Deterministic fallback keeps escalation working without a style
            # engine (e.g. in tests) — no decision depends on this.
            return template.format_map(_SafeDict(fields))
        return self._style.render_escalation(template, fields)

    # -- versioning -------------------------------------------------------
    def snapshot(self) -> EthosSnapshot:
        style_profile = {}
        if self._style is not None:
            style_profile = {"engine": type(self._style).__name__}
        return snapshot(
            judgment_policy={"engine": "JudgmentEngine", "version": "v0"},
            style_profile=style_profile,
            profile_id=self._profile.id if self._profile else None,
            profile_version=self._profile.version if self._profile else None,
        )


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
