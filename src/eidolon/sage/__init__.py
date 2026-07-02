"""SAGE adapter — the only path to the consensus memory + attestation ledger.

No other EIDOLON component talks to SAGE directly (PRD §6.1). The substrate is
isolated behind :class:`SagePort` so the fast test lane can use an in-memory
implementation while production binds the live SageClient SDK.
"""

from eidolon.sage.memory_fake import InMemorySagePort
from eidolon.sage.port import Attestation, Memory, ReplayFilter, SagePort, Scope

__all__ = [
    "SagePort",
    "Memory",
    "Attestation",
    "ReplayFilter",
    "Scope",
    "InMemorySagePort",
    "get_sage",
]


def get_sage() -> SagePort:
    """Return the configured SAGE port (memory fake or live SDK adapter)."""
    from eidolon.config import get_settings

    settings = get_settings()
    if settings.sage_backend == "sage":
        from eidolon.sage.client_adapter import SageClientAdapter

        return SageClientAdapter.from_settings(settings)
    return InMemorySagePort()
