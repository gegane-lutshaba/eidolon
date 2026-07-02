"""Capture pipeline (PRD §6.7).

Passively ingest the principal's consented traces into SAGE as
provenance-tagged observations that feed ETHOS. No source is ingested without an
explicit, principal-owned ``ConsentGrant``; every observation carries source
provenance.
"""

from eidolon.capture.connector import (
    Connector,
    ConsentGrant,
    DocsMessagesConnector,
    MCPSourceConnector,
    SourceSpec,
    Trace,
    connect,
    known_sources,
    register_source,
)
from eidolon.capture.ingest import ingest, ingest_all

__all__ = [
    "Connector",
    "ConsentGrant",
    "Trace",
    "DocsMessagesConnector",
    "MCPSourceConnector",
    "SourceSpec",
    "connect",
    "register_source",
    "known_sources",
    "ingest",
    "ingest_all",
]
