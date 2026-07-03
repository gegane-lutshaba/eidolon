"""Tool → capability-class mapping (fail-closed).

A downstream MCP tool (``delete_database``, ``send_customer_email``,
``get_deploy_status``) is mapped to a Domain Profile capability class so KAIROS
can govern it. Mapping is declarative:

- explicit per-tool policy (class + which exclusion boundaries the tool touches,
  its scope, its budget cost);
- an optional derivation from the profile's ``tool_bindings`` (matching a tool
  name against the bound ``mcp_tool_ref``);
- otherwise the **fail-closed default**: an unmapped tool is treated as the most
  dangerous, always-escalate class, so an unknown tool can never act unattended
  (default-deny for capability classification).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from eidolon.profile.schema import DomainProfile
from eidolon.sage.port import Scope


class ToolPolicy(BaseModel):
    """How one downstream tool is governed."""

    model_config = {"frozen": True}

    tool: str
    action_class: str
    # Exclusion boundaries this tool implicates (e.g. an email tool touches
    # "external-client-comm"; a delete tool touches "destructive-action").
    touches_exclusions: list[str] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    # Derive scope selectors from the call's arguments so a call is bounded by
    # what it actually targets, e.g. {"target": "host"} sets scope target = the
    # value of the "host" argument. THEMIS then denies out-of-grant targets.
    scope_from_args: dict[str, str] = Field(default_factory=dict)
    budget_cost: dict[str, int] = Field(default_factory=dict)

    def resolved_scope(self, arguments: dict) -> Scope:
        selectors = {k: list(v) for k, v in self.scope.selectors.items()}
        for selector_type, arg_key in self.scope_from_args.items():
            if arg_key in arguments and arguments[arg_key] is not None:
                selectors[selector_type] = [str(arguments[arg_key])]
        return Scope(selectors=selectors)


class ToolPolicyMap:
    """Resolve a tool name to a :class:`ToolPolicy`, fail-closed."""

    def __init__(
        self,
        profile: DomainProfile,
        policies: list[ToolPolicy] | None = None,
        *,
        default_scope: Scope | None = None,
        default_class: str | None = None,
    ) -> None:
        self._profile = profile
        self._by_tool = {p.tool: p for p in (policies or [])}
        self._default_scope = default_scope or Scope()
        # Fail-closed: unmapped tools get an always-escalate class if the profile
        # declares one, else the highest-risk class.
        self._default_class = default_class or _most_dangerous_class(profile)
        # Reverse index of the profile's own tool_bindings (mcp_tool_ref -> class).
        self._by_ref = {b.mcp_tool_ref: b.class_ for b in profile.tool_bindings}

    def policy_for(self, tool: str) -> ToolPolicy:
        if tool in self._by_tool:
            return self._by_tool[tool]
        # A tool named exactly like a profile tool_binding ref inherits its class.
        if tool in self._by_ref:
            return ToolPolicy(tool=tool, action_class=self._by_ref[tool], scope=self._default_scope)
        return ToolPolicy(tool=tool, action_class=self._default_class, scope=self._default_scope)

    @property
    def default_class(self) -> str:
        return self._default_class


def _most_dangerous_class(profile: DomainProfile) -> str:
    """Pick the safest fallback: an always-escalate class, else highest risk_tier."""
    escalate = profile.mandate_schema.escalation_required
    if escalate:
        return escalate[0]
    ranked = sorted(profile.capability_taxonomy, key=lambda c: int(c.risk_tier), reverse=True)
    return ranked[0].class_ if ranked else "commit-action"
