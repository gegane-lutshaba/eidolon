"""The coach (PRD §12 v2).

Observes the twin's actual behavior (from the HORKOS attestation ledger) and its
policy evolution (from ETHOS version diffs), compares both against the
principal's declared :class:`Aspiration`, and returns advisory
:class:`CoachingReport`s.

Strictly read-only and decoupled: the coach depends on the SAGE replay path and
ETHOS versioning, but NO decision-path component depends on it, and it writes
nothing back to the operating model or to judgment-visible memory.
"""

from __future__ import annotations

from eidolon.coaching.types import (
    Aspiration,
    BehaviorSummary,
    CoachingNote,
    CoachingReport,
    DriftReport,
)
from eidolon.ethos.versioning import EthosSnapshot, diff_snapshots
from eidolon.sage.port import Attestation

# How far observed behavior may sit from an aspiration target before the coach
# raises a nudge.
_RATE_TOLERANCE = 0.15

# Acting autonomy levels recorded on attestations.
_ACTING = {"DRAFT", "NOTIFY_ACT", "AUTONOMOUS_ACT"}


class Coach:
    """Aspirational-self coach. Construct freely; it holds no live state."""

    # -- behavior observation --------------------------------------------
    def summarize_behavior(self, attestations: list[Attestation]) -> list[BehaviorSummary]:
        """Aggregate the attestation ledger into per-class behavior summaries."""
        by_class: dict[str, list[Attestation]] = {}
        for a in attestations:
            by_class.setdefault(a.action_class, []).append(a)

        summaries: list[BehaviorSummary] = []
        for cls, records in sorted(by_class.items()):
            escalations = sum(1 for r in records if r.would_have_escalated or r.autonomy_level == "ESCALATE")
            acted = sum(1 for r in records if r.autonomy_level in _ACTING)
            confidences = [r.confidence for r in records if r.confidence is not None]
            avg_conf = sum(confidences) / len(confidences) if confidences else None
            summaries.append(
                BehaviorSummary(
                    action_class=cls,
                    decisions=len(records),
                    escalations=escalations,
                    acted=acted,
                    avg_confidence=round(avg_conf, 4) if avg_conf is not None else None,
                )
            )
        return summaries

    # -- ETHOS policy drift ----------------------------------------------
    def drift(self, earlier: EthosSnapshot, later: EthosSnapshot) -> DriftReport:
        """Read an ETHOS version diff as a drift report."""
        d = diff_snapshots(earlier, later)
        return DriftReport(
            version_from=d["version_from"],
            version_to=d["version_to"],
            changed=d["changed"],
        )

    # -- coaching ---------------------------------------------------------
    def coach(
        self,
        aspiration: Aspiration,
        attestations: list[Attestation],
        *,
        snapshots: tuple[EthosSnapshot, EthosSnapshot] | None = None,
    ) -> CoachingReport:
        behavior = self.summarize_behavior(attestations)
        by_class = {b.action_class: b for b in behavior}
        notes: list[CoachingNote] = []

        for target in aspiration.targets:
            b = by_class.get(target.action_class)
            if b is None or b.decisions == 0:
                continue
            notes.extend(self._target_notes(target, b))

        # Surface declared values as reminders (not measurable, still coached).
        for value in aspiration.values:
            notes.append(
                CoachingNote(
                    topic="value",
                    observation="A principle you asked to be held to.",
                    suggestion=value,
                    severity="info",
                )
            )

        drift = None
        if snapshots is not None:
            drift = self.drift(snapshots[0], snapshots[1])
            if drift.drifted:
                notes.append(
                    CoachingNote(
                        topic="policy-drift",
                        observation=(
                            f"Your judgment policy changed between {drift.version_from} "
                            f"and {drift.version_to}: {sorted(drift.changed)}."
                        ),
                        suggestion="Review whether this drift moves toward your stated aspirations.",
                        severity="nudge",
                    )
                )

        return CoachingReport(
            principal_id=aspiration.principal_id,
            notes=notes,
            behavior=behavior,
            drift=drift,
        )

    # -- internals --------------------------------------------------------
    def _target_notes(self, target, behavior: BehaviorSummary) -> list[CoachingNote]:  # noqa: ANN001
        notes: list[CoachingNote] = []
        cls = target.action_class

        if target.target_escalation_rate is not None:
            observed = behavior.escalation_rate
            gap = observed - target.target_escalation_rate
            if gap < -_RATE_TOLERANCE:
                notes.append(
                    CoachingNote(
                        topic="under-escalating",
                        observation=(
                            f"On {cls} you escalated {observed:.0%} of the time; you "
                            f"aspired to {target.target_escalation_rate:.0%}."
                        ),
                        suggestion=f"Consider handing more {cls} decisions back to yourself.",
                        severity="flag",
                    )
                )
            elif gap > _RATE_TOLERANCE:
                notes.append(
                    CoachingNote(
                        topic="over-escalating",
                        observation=(
                            f"On {cls} you escalated {observed:.0%}, above your "
                            f"{target.target_escalation_rate:.0%} aspiration."
                        ),
                        suggestion=f"You may be able to trust the twin with more {cls} decisions.",
                        severity="nudge",
                    )
                )

        if target.min_confidence_to_act is not None and behavior.avg_confidence is not None:
            if behavior.acted and behavior.avg_confidence < target.min_confidence_to_act:
                notes.append(
                    CoachingNote(
                        topic="acting-on-thin-confidence",
                        observation=(
                            f"On {cls} you acted at avg confidence "
                            f"{behavior.avg_confidence:.2f}, below your "
                            f"{target.min_confidence_to_act:.2f} bar."
                        ),
                        suggestion=f"Raise the confidence threshold for {cls} before acting.",
                        severity="flag",
                    )
                )

        if target.note:
            notes.append(
                CoachingNote(
                    topic="aspiration",
                    observation=f"Your note on {cls}.",
                    suggestion=target.note,
                    severity="info",
                )
            )
        return notes
