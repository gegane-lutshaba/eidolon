"""Gateway → platform reporting (mission control).

After each governed decision the gateway POSTs a redacted event to the
platform's ``/ingest/events`` and reads back the **kill state**. Telemetry
never weakens the gate:

- best-effort with a short timeout — an unreachable platform dims the
  dashboard, it never blocks or loosens a tool call;
- the kill switch only ever *tightens*: once the platform says ``killed``,
  the gateway refuses acting calls until a later report says otherwise.
"""

from __future__ import annotations

from typing import Any

# Reported instead of a gate level when the operator has killed the gateway.
KILLED_LEVEL = "KILLED"


class Reporter:
    def __init__(
        self,
        url: str,
        key: str | None = None,
        *,
        gateway_id: str = "gateway",
        agent: str = "",
        timeout: float = 2.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._key = key
        self._gateway_id = gateway_id
        self._agent = agent
        self._timeout = timeout
        self.killed = False

    def report(
        self,
        *,
        tool: str,
        action_class: str,
        level: str,
        allowed: bool,
        attestation_hash: str | None,
        summary: str = "",
        rationale: str = "",
    ) -> bool:
        """POST one event; update and return the kill state (True = killed)."""
        try:
            import httpx

            headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
            r = httpx.post(
                f"{self._url}/ingest/events",
                json={
                    "gateway_id": self._gateway_id, "agent": self._agent,
                    "tool": tool, "action_class": action_class, "level": level,
                    "allowed": allowed, "attestation_hash": attestation_hash,
                    "summary": summary, "rationale": rationale,
                },
                headers=headers, timeout=self._timeout,
            )
            if r.status_code == 200:
                self.killed = bool(r.json().get("killed", False))
        except Exception:  # noqa: BLE001 — telemetry must never break the gate
            pass  # keep the last known kill state (tighten-only semantics)
        return self.killed

    def report_result(self, result: Any, summary: str = "") -> bool:
        """Convenience: report a :class:`GovernedResult`-shaped object."""
        return self.report(
            tool=result.tool, action_class=result.action_class, level=result.level,
            allowed=result.allowed, attestation_hash=result.attestation_hash,
            summary=summary, rationale=result.rationale,
        )
