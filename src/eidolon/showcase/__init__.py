"""Showcase scenarios as structured data (for the web dashboard + tests).

Runs the real EIDOLON core and returns a :class:`ScenarioResult` — the same
"twin while you're away" story the CLI demo narrates, but as JSON-serializable
models a UI can render. Nothing here is faked; every beat is a genuine
``KAIROS.resolve``.
"""

from eidolon.showcase.scenario import (
    Beat,
    DelegationView,
    LedgerRow,
    ScenarioResult,
    continuity_scenario,
    offensive_scenario,
)

__all__ = [
    "Beat",
    "DelegationView",
    "LedgerRow",
    "ScenarioResult",
    "continuity_scenario",
    "offensive_scenario",
]
