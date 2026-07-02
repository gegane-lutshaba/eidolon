"""Deterministic serialization + hashing — the single source of truth.

THEMIS credential signing, ETHOS versioning, and HORKOS attestation hashing all
route through here so that identical logical content always yields identical
bytes and therefore identical hashes. This is what makes attestations
tamper-evident and ETHOS snapshots diff-able (PRD §6.2, §6.5).

Rules:
- Object keys are sorted.
- No insignificant whitespace (compact separators).
- UTF-8, with non-ASCII preserved (ensure_ascii=False) so equal strings hash
  equal regardless of escaping.
- ``datetime`` is emitted as a normalized ISO-8601 string in UTC.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

from pydantic import BaseModel


def _default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        # mode="json" turns nested datetimes/enums into JSON-native scalars.
        return obj.model_dump(mode="json")
    if isinstance(obj, _dt.datetime):
        dt = obj.astimezone(_dt.UTC) if obj.tzinfo else obj.replace(tzinfo=_dt.UTC)
        return dt.isoformat()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, bytes):
        return obj.hex()
    raise TypeError(f"Cannot canonicalize object of type {type(obj)!r}")


def canonical_json(value: Any) -> str:
    """Return the canonical JSON string for ``value``."""
    return json.dumps(
        value,
        default=_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def content_hash(value: Any) -> str:
    """SHA-256 hex digest of the canonical bytes.

    Mirrors SAGE's ``content_hash`` semantics so an attestation's local hash and
    the ledger's hash agree.
    """
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
