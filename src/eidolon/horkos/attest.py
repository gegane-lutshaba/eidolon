"""HORKOS attestation writer + forensic replay (PRD §6.5).

    attest(record) -> hash            # via the SAGE adapter
    replay(filter) -> [Attestation]

The record is signed (Ed25519) before it is written so an attestation is
attributable and tamper-evident independently of the ledger, then persisted on
SAGE's consensus ledger where its content_hash is the authoritative ledger hash.
"""

from __future__ import annotations

from eidolon.common import crypto
from eidolon.common.canonical import canonical_bytes
from eidolon.sage.port import Attestation, ReplayFilter, SagePort


class Horkos:
    def __init__(self, sage: SagePort, *, signing_key_hex: str | None = None) -> None:
        self._sage = sage
        self._signing_key_hex = signing_key_hex

    def attest(self, record: Attestation) -> str:
        """Sign (if a key is configured) and write the attestation. Returns the
        ledger hash. Raises if the ledger write fails so KAIROS can abort."""
        if self._signing_key_hex and record.signature is None:
            unsigned = record.model_copy(update={"signature": None})
            signature = crypto.sign(self._signing_key_hex, canonical_bytes(unsigned))
            record = record.model_copy(update={"signature": signature})
        return self._sage.attest(record)

    def replay(self, filter: ReplayFilter) -> list[Attestation]:
        return self._sage.replay(filter)
