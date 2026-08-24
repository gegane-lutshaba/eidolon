"""EIDOLON governing MCP gateway — the *authority layer* for any MCP agent.

SAGE became "the memory layer" that agents plug in via MCP; EIDOLON is the
authority layer with the same shape. The gateway is an MCP proxy: an agent
(Hermes, Claude Code, OpenClaw, Raptor, Cursor…) points at it instead of a raw
tool server, and every ``tools/call`` is routed through KAIROS — THEMIS
authority, ETHOS fidelity, BASANOS ceiling, HORKOS attestation — before it can
touch the real tool. No changes to the agent.

    agent ──MCP──▶ eidolon-gateway ──(KAIROS.resolve)──▶ real MCP tool server
                        │ attest-then-forward
                        ▼
                   SAGE ledger

The governance core (:class:`GovernanceEngine`) is transport-free and fully
testable; :mod:`eidolon.gateway.server` is a thin MCP adapter over it.
"""

from eidolon.gateway.engine import GovernanceEngine, GovernedResult
from eidolon.gateway.mapping import ToolPolicy, ToolPolicyMap
from eidolon.gateway.purpose import PurposeTracker
from eidolon.gateway.taint import TaintTracker

__all__ = ["GovernanceEngine", "GovernedResult", "ToolPolicy", "ToolPolicyMap",
           "TaintTracker", "PurposeTracker"]
