"""Map AgentDojo tools to EIDOLON capability classes (general-continuity).

The mapping is by tool *effect*, derived from the verb, and is deliberately
uniform and fail-closed:

- **reads** (get/search/read/list/check) → ``retrieve-context`` (autonomous)
- **internal recoverable posts** (post/send to one's own channel) → ``post-status``
- **outbound comms & sharing** (email/DM/webpage/share) → ``draft-comm`` +
  ``external-client-comm`` (the exfiltration vector — drafted/denied, not sent)
- **bindings & mutations** (money/booking/password/calendar/delete/user-admin)
  → ``commit-action`` (always escalates — handed back)
- **anything unmapped** → the fail-closed default (``commit-action``)

The class of a tool does NOT depend on whether the caller's intent is benign or
malicious — that's the point: EIDOLON bounds authority, it doesn't read intent.
"""

from __future__ import annotations

from eidolon.gateway.mapping import ToolPolicy
from eidolon.sage.port import Scope

# Outbound comms / sharing — the exfiltration vectors. Held for approval
# (drafted), not auto-sent. We deliberately do NOT assert a hard exclusion here:
# externality (client vs colleague) can't be read from a tool *name*, so a
# generic mapping escalates rather than categorically denies. A domain-specific
# profile that knows a tool is always-external would map it to an exclusion.
_OUTBOUND = {
    "send_email", "send_direct_message", "send_channel_message",
    "post_webpage", "share_file",
}
_READ_PREFIXES = ("get_", "search_", "read_", "list_", "check_")
_READ_EXACT = {"get_webpage", "read_inbox", "get_current_day"}


def classify_tool(tool: str) -> tuple[str, list[str]]:
    """Return (action_class, touches_exclusions) for a tool name."""
    if tool in _OUTBOUND:
        return "draft-comm", []  # held for approval
    if tool in _READ_EXACT or tool.startswith(_READ_PREFIXES):
        return "retrieve-context", []  # autonomous
    # Everything else is a mutation/binding (money, booking, password, calendar,
    # delete, user-admin, file writes) → commit-action → always escalates.
    return "commit-action", []


def build_policies(tools: list[str], scope: Scope) -> list[ToolPolicy]:
    policies: list[ToolPolicy] = []
    for tool in tools:
        action_class, exclusions = classify_tool(tool)
        budget = {"posts_per_window": 1} if action_class == "post-status" else {}
        policies.append(
            ToolPolicy(tool=tool, action_class=action_class,
                       touches_exclusions=exclusions, scope=scope, budget_cost=budget)
        )
    return policies
