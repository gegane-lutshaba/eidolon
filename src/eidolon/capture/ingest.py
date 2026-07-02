"""Trace -> observation ingestion (PRD §6.7, §P0.2.3).

Writes each connector trace into SAGE as a provenance-tagged observation. The
connector has already enforced consent; ingestion just persists. Returns the
list of created ``mem_id``s so ingested traces are immediately recallable.
"""

from __future__ import annotations

from eidolon.capture.connector import Connector
from eidolon.sage.port import SagePort


def ingest(sage: SagePort, connector: Connector) -> list[str]:
    mem_ids: list[str] = []
    for trace in connector.traces():
        mem_id = sage.observe(
            principal_id=connector.principal_id,
            content=trace.content,
            type="observation",
            provenance=trace.provenance,
            scope=trace.scope,
        )
        mem_ids.append(mem_id)
    return mem_ids
