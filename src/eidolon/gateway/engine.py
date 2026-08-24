"""Governance engine — govern one MCP tool call through KAIROS.

Transport-free and fully testable. Given a downstream tool call, it maps the
tool to a capability class, resolves it through the gate, and — ONLY when the
gate authorizes an acting level — forwards to the real tool. Everything else
(draft / escalate / deny) returns a structured refusal instead of the result.

Attest-then-act holds end-to-end: ``KAIROS.resolve`` writes the attestation
before it returns, so the real side effect (``forward``) always runs *after* a
successful attestation — never before, never without one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from eidolon.basanos.certify import Certificate
from eidolon.basanos.integrity.report import IntegrityCertificate
from eidolon.gateway.mapping import ToolPolicyMap
from eidolon.gateway.taint import TaintTracker
from eidolon.kairos.gate import Kairos
from eidolon.kairos.types import DecisionLevel
from eidolon.themis.types import Delegation
from eidolon.types import Action, Context

# Levels at which the real tool is actually invoked.
_ACTING = {DecisionLevel.NOTIFY_ACT, DecisionLevel.AUTONOMOUS_ACT}

ForwardFn = Callable[[str, dict], Any]


class GovernedResult(BaseModel):
    """Outcome of governing a single tool call."""

    tool: str
    action_class: str
    level: str
    allowed: bool  # True iff the real downstream tool was executed
    attestation_hash: str | None = None
    rationale: str = ""
    # For refusals/drafts: what the agent gets back instead of the tool result.
    message: str | None = None
    # For allowed calls: the real downstream tool result (opaque).
    result: Any | None = None
    forward_error: str | None = None


class GovernanceEngine:
    def __init__(
        self,
        *,
        kairos: Kairos,
        policy_map: ToolPolicyMap,
        chain: list[Delegation],
        principal_id: str,
        certificates: list[Certificate] | None = None,
        integrity_certificate: IntegrityCertificate | None = None,
        taint: TaintTracker | None = None,
    ) -> None:
        self._kairos = kairos
        self._policies = policy_map
        self._chain = chain
        self._principal_id = principal_id
        self._certs = certificates or []
        self._icert = integrity_certificate
        self._taint = taint

    def decide(self, tool: str, arguments: dict) -> GovernedResult:
        """Govern a tool call WITHOUT forwarding (sync). ``allowed`` means the
        gate authorized an acting level; the caller performs the side effect.

        This lets an async MCP server run the sync gate here, then ``await`` the
        real downstream call itself — attestation is already written by the time
        this returns, so attest-then-act holds either way.
        """
        policy = self._policies.policy_for(tool)
        summary = _summarize(arguments)
        # Data-flow layer: if a sensitive value learned from a prior read is
        # flowing out through this egress call, mark it as exfiltration. The gate
        # then denies-and-attests it via the normal exclusion path — authority
        # and data-flow compose through one mechanism.
        exclusions = list(policy.touches_exclusions)
        if self._taint is not None:
            exclusions += self._taint.exfiltration_exclusions(tool, arguments)
        action = Action(
            id=f"tool:{tool}",
            action_class=policy.action_class,
            description=f"call tool {tool}" + (f" with {summary}" if summary else ""),
            scope=policy.resolved_scope(arguments),
            touches_exclusions=exclusions,
            budget_cost=policy.budget_cost,
        )
        # Arguments are UNTRUSTED and ride in context_text; KAIROS re-checks
        # authority independently, so an injected arg can't widen the verdict.
        context = Context(
            principal_id=self._principal_id,
            query=f"{tool.replace('_', ' ')} {summary}".strip(),
            context_text=_safe_json(arguments),
            situation=f"the {tool} tool",
        )
        decision = self._kairos.resolve(action, context, self._chain, self._certs, self._icert)
        acting = decision.level in _ACTING
        return GovernedResult(
            tool=tool, action_class=policy.action_class, level=decision.level.value,
            allowed=acting, attestation_hash=decision.attestation_hash,
            rationale=decision.rationale,
            message=None if acting else (decision.output or _refusal_message(decision.level, decision.rationale)),
        )

    def govern(self, tool: str, arguments: dict, forward: ForwardFn | None = None) -> GovernedResult:
        """Govern AND forward (sync). Forwards to the real tool only when the
        gate authorized an acting level; otherwise returns the refusal/draft."""
        result = self.decide(tool, arguments)
        if not result.allowed:
            return result
        if forward is None:
            return result.model_copy(update={"message": "authorized; no downstream bound (dry-run)"})
        try:
            output = forward(tool, arguments)
        except Exception as exc:  # noqa: BLE001 — surface tool failure, don't crash the gateway
            return result.model_copy(update={"forward_error": str(exc)})
        # Data-flow: learn any sensitive values this (permitted) read returned, so
        # a later egress carrying them is caught as exfiltration.
        self.observe_result(tool, output)
        return result.model_copy(update={"result": output})

    def observe_result(self, tool: str, result: object) -> None:
        """Feed a forwarded tool's output to the taint tracker (data-flow layer).

        The async MCP server must call this after it awaits a downstream result.
        """
        if self._taint is not None:
            self._taint.observe(tool, result)


def _summarize(arguments: dict, limit: int = 160) -> str:
    if not arguments:
        return ""
    parts = [f"{k}={_short(v)}" for k, v in arguments.items()]
    s = ", ".join(parts)
    return s[:limit]


def _short(v: Any, n: int = 40) -> str:
    s = str(v)
    return s if len(s) <= n else s[:n] + "…"


def _safe_json(arguments: dict) -> str:
    try:
        return json.dumps(arguments, default=str)[:2000]
    except Exception:
        return str(arguments)[:2000]


def _refusal_message(level: DecisionLevel, rationale: str) -> str:
    if level == DecisionLevel.DENY:
        return f"EIDOLON denied this tool call: {rationale}"
    if level == DecisionLevel.ESCALATE:
        return f"EIDOLON escalated this to the principal (not executed): {rationale}"
    if level == DecisionLevel.DRAFT:
        return f"EIDOLON prepared a draft for approval (not executed): {rationale}"
    return rationale
