"""Evaluation harnesses for EIDOLON.

``agentdojo_eval`` measures EIDOLON's *enforcement contribution* over the real
AgentDojo tasks and tools (Debenedetti et al.), deterministically and without
paying for LLM runs: each task ships ground-truth tool calls, and EIDOLON's
governing gateway either permits or contains each call. This isolates exactly
the layer EIDOLON operates at (authority over tool calls) and is fully
reproducible. See ``docs/eval-agentdojo.md``.
"""

from eidolon.eval.agentdojo_policy import build_policies, classify_tool

__all__ = ["build_policies", "classify_tool"]
