"""KAIROS resolution gate (PRD §6.4, LOCKED order).

    resolve(action, context, chain, certificates) -> Decision{level, rationale, attestation_hash}

LOCKED order:
  1. THEMIS.verify -> invalid ⇒ DENY. Class in escalation_required, or budget
     exceeded ⇒ ESCALATE. (Authority is re-checked here independently of memory
     content, so injected instructions in context/memory can never flip it.)
  2. ETHOS.evaluate -> confidence < threshold(class) or STOP ⇒ ESCALATE.
     PROCEED_WITH_CARE ⇒ DRAFT (caps the level at draft).
  3. level = min(cred.max_autonomy, BASANOS.autonomy_ceiling(class), config.dial).
  4. Execute at level; call HORKOS.attest BEFORE any side effect commits
     (attest-then-act). On attest failure ⇒ abort.

Structural guarantee: the ONLY place this module executes a side effect is
``_execute``, and it is unreachable except after ``_attest`` has returned a hash.
"""

from __future__ import annotations

from eidolon.basanos.certify import Basanos, Certificate
from eidolon.basanos.integrity.report import IntegrityCertificate
from eidolon.common.errors import AttestationFailed
from eidolon.config import Settings, get_settings
from eidolon.ethos.facade import Ethos
from eidolon.ethos.types import Decision as EthosDecision
from eidolon.ethos.types import Judgment
from eidolon.horkos.attest import Horkos
from eidolon.kairos.types import BudgetLedger, Decision, DecisionLevel, level_for_autonomy
from eidolon.profile.schema import DomainProfile, min_autonomy
from eidolon.sage.port import Attestation, SagePort, now_utc
from eidolon.themis.engine import Themis
from eidolon.themis.types import Delegation
from eidolon.types import Action, Context


class Kairos:
    def __init__(
        self,
        *,
        themis: Themis,
        ethos: Ethos,
        basanos: Basanos,
        horkos: Horkos,
        sage: SagePort,
        profile: DomainProfile,
        settings: Settings | None = None,
        budget: BudgetLedger | None = None,
    ) -> None:
        self._themis = themis
        self._ethos = ethos
        self._basanos = basanos
        self._horkos = horkos
        self._sage = sage
        self._profile = profile
        self._settings = settings or get_settings()
        self._budget = budget or BudgetLedger()

    def resolve(
        self,
        action: Action,
        context: Context,
        chain: list[Delegation],
        certificates: list[Certificate] | None = None,
        integrity_certificate: IntegrityCertificate | None = None,
    ) -> Decision:
        certificates = certificates or []

        # -- Step 1: authority (independent of memory content) ------------
        cred = self._themis.verify(action, chain)
        if not cred.valid:
            return self._finalize(
                DecisionLevel.DENY,
                f"authority denied: {cred.reason}",
                action,
                context,
                chain,
                judgment=None,
                would_have_escalated=False,
            )
        effective = cred.effective
        assert effective is not None

        if self._profile.always_escalates(action.action_class) or (
            action.action_class in effective.escalation_required
        ):
            return self._escalate(
                "out-of-scope",
                {"boundary": action.action_class, "principal": context.principal_id,
                 "situation": context.situation},
                action, context, chain, judgment=None,
            )

        exceeded = self._budget.would_exceed(
            context.principal_id, action.budget_cost, effective.blast_radius_budget
        )
        if exceeded:
            return self._escalate(
                "out-of-scope",
                {"boundary": f"budget:{exceeded}", "principal": context.principal_id,
                 "situation": context.situation},
                action, context, chain, judgment=None,
            )

        # -- Step 2: fidelity ---------------------------------------------
        memories = self._sage.recall(
            context.principal_id, action.scope, context.query or action.description, 8
        )
        judgment = self._ethos.evaluate(action, context, memories, self._profile)
        threshold = self._ethos.confidence_threshold(action.action_class, self._profile)

        if judgment.decision == EthosDecision.STOP or judgment.confidence < threshold:
            return self._escalate(
                "low-confidence",
                {"principal": context.principal_id, "situation": context.situation or action.description},
                action, context, chain, judgment=judgment,
            )

        # PROCEED_WITH_CARE caps the outcome at DRAFT.
        care = judgment.decision == EthosDecision.PROCEED_WITH_CARE

        # -- Step 3: autonomy ceiling = min(cred, basanos, dial) ----------
        # BASANOS ceiling folds in fidelity and — when integrity gating is on —
        # adversarial-robustness certification (v2). A profile may REQUIRE
        # integrity certification by construction (e.g. offensive-security), so
        # gating is on if either the global config or the profile demands it.
        require_integrity = (
            self._settings.require_integrity_certification
            or self._profile.requires_integrity_certification
        )
        basanos_ceiling = self._basanos.gated_ceiling(
            action.action_class,
            certificates,
            integrity_certificate,
            require_integrity=require_integrity,
        )
        autonomy = min_autonomy(
            effective.max_autonomy, basanos_ceiling, self._settings.autonomy_dial
        )
        if care:
            autonomy = min_autonomy(autonomy, "draft")
        level = level_for_autonomy(autonomy)

        # An action that resolves to ESCALATE (observe ceiling) is handed back.
        if level == DecisionLevel.ESCALATE:
            return self._escalate(
                "low-confidence",
                {"principal": context.principal_id, "situation": context.situation or action.description},
                action, context, chain, judgment=judgment,
            )

        # -- Step 4: attest-then-act --------------------------------------
        return self._finalize(
            level,
            f"authorized at {level.value}: {judgment.rationale}",
            action, context, chain,
            judgment=judgment,
            would_have_escalated=False,
        )

    # -- escalation -------------------------------------------------------
    def _escalate(self, trigger, fields, action, context, chain, *, judgment) -> Decision:
        template = self._template(trigger)
        message = self._ethos.render_escalation(template, fields) if template else "Escalating."
        return self._finalize(
            DecisionLevel.ESCALATE,
            f"escalated ({trigger})",
            action, context, chain,
            judgment=judgment,
            would_have_escalated=True,
            output=message,
        )

    def _template(self, trigger: str) -> str | None:
        for t in self._profile.escalation_templates:
            if t.trigger == trigger:
                return t.message_template
        return None

    # -- finalize (attest-then-act) --------------------------------------
    def _finalize(
        self,
        level: DecisionLevel,
        rationale: str,
        action: Action,
        context: Context,
        chain: list[Delegation],
        *,
        judgment: Judgment | None,
        would_have_escalated: bool,
        output: str | None = None,
    ) -> Decision:
        record = Attestation(
            action=action.description,
            action_class=action.action_class,
            timestamp=now_utc(),
            delegation_chain=[d.id for d in chain],
            evidence_refs=judgment.evidence_refs if judgment else [],
            ethos_version=self._ethos.snapshot().version,
            judgment=judgment.decision.value if judgment else None,
            confidence=judgment.confidence if judgment else None,
            autonomy_level=level.value,
            result="pending",
            would_have_escalated=would_have_escalated,
            principal_id=context.principal_id,
        )

        # ATTEST BEFORE ANY SIDE EFFECT. If this fails, we never execute.
        try:
            attestation_hash = self._horkos.attest(record)
        except Exception as exc:  # noqa: BLE001
            raise AttestationFailed(f"attestation failed; action aborted: {exc}") from exc

        # Only now may a side effect run. DENY/ESCALATE/DRAFT are non-committing;
        # NOTIFY_ACT/AUTONOMOUS_ACT execute the bound tool.
        if output is None:
            output = self._execute(level, action, context)

        return Decision(
            level=level,
            rationale=rationale,
            attestation_hash=attestation_hash,
            output=output,
            action_class=action.action_class,
        )

    def _execute(self, level: DecisionLevel, action: Action, context: Context) -> str | None:
        """The single, gated side-effect site. Reached only post-attestation."""
        if level == DecisionLevel.DRAFT:
            # Render a draft for approval (style engine; not sent anywhere).
            return self._ethos.draft(action, context, self._profile)
        if level in (DecisionLevel.NOTIFY_ACT, DecisionLevel.AUTONOMOUS_ACT):
            # A recoverable/reversible side effect commits here. Consume budget.
            self._budget.consume(context.principal_id, action.budget_cost)
            tool = self._profile.tool_for(action.action_class)
            return f"executed via {tool or 'bound tool'} at {level.value}"
        return None
