"""Purpose-binding — data-flow with a *purpose* dimension (privacy limitation).

Beyond "is this data sensitive?" (taint) lies "may this data be used *for this
purpose*?" — the GDPR-style purpose-limitation principle that ToolPrivacyBench
(Purpose-Bound Privacy in Tool-Using LLM Agents) measures.

Data returned by a read carries the **purpose it was collected for** (declared on
the read tool's policy). When a value flows into a tool that serves a *different*
purpose, that is a purpose violation — even if the class/authority permits the
call and even if the sink is otherwise allowed. Like the taint layer, the tracker
doesn't decide: it derives a dynamic ``purpose-limitation`` exclusion that the
KAIROS gate denies and attests.

Compatibility is exact-match by default (strict limitation); a compatibility map
can allow declared secondary uses.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from eidolon.gateway.taint import extract_values

# Marker exclusion produced when data crosses a purpose boundary.
PURPOSE_LIMITATION = "purpose-limitation"


class PurposeTracker:
    """Session-scoped value → collected-purpose tracker."""

    def __init__(self, *, compatible: Callable[[str, str], bool] | None = None) -> None:
        # collected purpose -> allowed use purposes. Default: exact match only.
        self._compatible = compatible or (lambda collected, used: collected == used)
        self._value_purpose: dict[str, str] = {}

    def observe(self, result: object, collected_purpose: str | None) -> None:
        """Tag the sensitive values a read returned with their collected purpose."""
        if not collected_purpose:
            return
        for v in extract_values(result):
            # First observation wins; a value keeps the purpose it was collected for.
            self._value_purpose.setdefault(v, collected_purpose)

    def purpose_violations(self, arguments: dict, used_purpose: str | None) -> list[str]:
        """``[PURPOSE_LIMITATION]`` if an argument carries a value collected for an
        incompatible purpose."""
        if used_purpose is None or not self._value_purpose:
            return []
        blob = json.dumps(arguments, default=str)
        for value, collected in self._value_purpose.items():
            if value in blob and not self._compatible(collected, used_purpose):
                return [PURPOSE_LIMITATION]
        return []

    @property
    def known_purposes(self) -> dict[str, str]:
        return dict(self._value_purpose)
