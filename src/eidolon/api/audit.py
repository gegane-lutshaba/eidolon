"""Audit console support: ledger integrity + compliance evidence export.

Pure helpers over a :class:`SagePort`'s attestation ledger, kept out of the
transport layer so they are unit-testable without HTTP:

- :func:`chain_status` — surface the Postgres port's hash-chain verification
  (``ok`` / ``broken_at``); degrade gracefully on backends that don't chain.
- :func:`evidence_bundle` — a self-describing, hash-sealed JSON bundle of the
  attestations for a query, suitable as SOC2 / EU AI Act evidence.
- :func:`ledger_csv` — the same records flattened to CSV.

Each row carries ``ledger_hash = H(attestation)`` so an exported record can be
cross-referenced against the on-box chain.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from eidolon.common.canonical import content_hash
from eidolon.sage.port import Attestation, ReplayFilter, SagePort, now_utc


def chain_status(sage: SagePort) -> dict[str, Any]:
    """Ledger tamper-evidence status. Only the Postgres port hash-chains; other
    backends report ``supported=False`` (consensus/ephemeral integrity model)."""
    verify = getattr(sage, "verify_chain", None)
    if verify is None:
        return {"supported": False, "backend": type(sage).__name__}
    status = verify()
    return {
        "supported": True,
        "ok": status.ok,
        "length": status.length,
        "broken_at": status.broken_at,
    }


def _row(rec: Attestation) -> dict[str, Any]:
    d = rec.model_dump(mode="json")
    d["ledger_hash"] = content_hash(rec)
    return d


def query_ledger(sage: SagePort, filt: ReplayFilter) -> list[Attestation]:
    return sage.replay(filt)


def evidence_bundle(
    sage: SagePort,
    filt: ReplayFilter,
    *,
    generated_at: Any | None = None,
) -> dict[str, Any]:
    """A hash-sealed evidence bundle: the matching attestations, the current
    chain status, and a ``bundle_hash`` over the whole payload so recipients can
    detect post-export tampering of the file itself."""
    records = sage.replay(filt)
    rows = [_row(r) for r in records]
    body = {
        "kind": "eidolon.evidence-bundle.v1",
        "generated_at": (generated_at or now_utc()),
        "filter": filt.model_dump(mode="json"),
        "chain": chain_status(sage),
        "count": len(rows),
        "attestations": rows,
    }
    body["bundle_hash"] = content_hash(body)
    return body


_CSV_COLUMNS = [
    "timestamp",
    "principal_id",
    "action",
    "action_class",
    "autonomy_level",
    "result",
    "confidence",
    "would_have_escalated",
    "ethos_version",
    "judgment",
    "evidence_refs",
    "delegation_depth",
    "ledger_hash",
]


def ledger_csv(sage: SagePort, filt: ReplayFilter) -> str:
    """Flatten the matching attestations to CSV (one row per governed action)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for rec in sage.replay(filt):
        w.writerow(
            {
                "timestamp": rec.timestamp.isoformat(),
                "principal_id": rec.principal_id,
                "action": rec.action,
                "action_class": rec.action_class,
                "autonomy_level": rec.autonomy_level or "",
                "result": rec.result or "",
                "confidence": "" if rec.confidence is None else rec.confidence,
                "would_have_escalated": rec.would_have_escalated,
                "ethos_version": rec.ethos_version or "",
                "judgment": (rec.judgment or "").replace("\n", " "),
                "evidence_refs": ";".join(rec.evidence_refs),
                "delegation_depth": len(rec.delegation_chain),
                "ledger_hash": content_hash(rec),
            }
        )
    return buf.getvalue()
