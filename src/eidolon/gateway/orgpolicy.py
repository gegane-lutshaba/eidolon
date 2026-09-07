"""Org-wide policy contributor for the managed engines (hosted MCP + coding hook).

An org admin sets guardrails every managed agent inherits. Two are enforced
per-call as dynamically-derived exclusions the gate denies-and-attests — composed
through the same mechanism as the taint/purpose layers:

- ``blocked_paths``: a path prefix an agent may not touch (matched against any
  read/edit/shell argument value).
- ``egress_allowlist``: if non-empty, an egress call whose URL targets a host not
  on the list is denied.

The third control, ``approval_classes``, is applied at engine-build time as a
credential *must-escalate* set (see ``gateway.config.build_engine``), so those
classes are handed to a human instead of acting.

The contributor fetches the current policy on every call, so path/egress changes
take effect immediately without rebuilding engines.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

# Exclusion strings — MUST also appear in each profile's mandate_schema
# .exclusion_types, so the credential reserves them and the gate denies.
PATH_EXCL = "org-restricted-path"
EGRESS_EXCL = "org-egress-blocked"

_URL_RE = re.compile(r"https?://([^/\s:@]+)", re.IGNORECASE)


def _flatten(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for v in value.values():
            yield from _flatten(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _flatten(v)
    elif value is not None:
        yield str(value)


def _host_ok(host: str, allow: list[str]) -> bool:
    host = host.lower().strip()
    for entry in allow:
        e = entry.lower().strip().lstrip("*.")
        if e and (host == e or host.endswith("." + e)):
            return True
    return False


class OrgPolicy:
    """Per-call org guardrails. ``fetch`` returns the current policy dict:
    {blocked_paths, egress_allowlist, approval_classes}."""

    def __init__(self, fetch: Callable[[], dict]) -> None:
        self._fetch = fetch

    def violations(self, tool: str, arguments: dict) -> list[str]:
        try:
            pol = self._fetch() or {}
        except Exception:  # noqa: BLE001 — policy lookup must never break the gate
            return []
        blocked = [p.strip().lower() for p in (pol.get("blocked_paths") or []) if p.strip()]
        allow = [h for h in (pol.get("egress_allowlist") or []) if h.strip()]
        values = list(_flatten(arguments))
        blob = " ".join(values)
        low = blob.lower()
        out: list[str] = []
        if blocked and any(p in low for p in blocked):
            out.append(PATH_EXCL)
        if allow:
            hosts = _URL_RE.findall(blob)
            if hosts and not all(_host_ok(h, allow) for h in hosts):
                out.append(EGRESS_EXCL)
        return out
