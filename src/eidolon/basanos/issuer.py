"""Server-side certificate issuance.

A fidelity certificate lifts a class's autonomy ceiling, so whoever can present
one controls how far an agent may act. Over the HTTP API a caller must not be able
to *assert* a certificate; it has to be *earned* by running BASANOS on the
server. The issuer signs what BASANOS produced (HMAC-SHA256 over the canonical
certificate, bound to one principal); the API then accepts only certificates
whose signature verifies for the acting principal.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from eidolon.basanos.certify import Certificate
from eidolon.common.canonical import canonical_bytes


class CertificateIssuer:
    def __init__(self, key: str | bytes | None = None) -> None:
        if key is None:
            key = secrets.token_bytes(32)  # per-process: certs valid in this process only
        self._key = key.encode() if isinstance(key, str) else key

    def _mac(self, cert: Certificate) -> str:
        body = cert.model_dump(mode="json", exclude={"issuer_sig"})
        return hmac.new(self._key, canonical_bytes(body), hashlib.sha256).hexdigest()

    def sign(self, cert: Certificate, principal_id: str) -> Certificate:
        bound = cert.model_copy(update={"principal_id": principal_id, "issuer_sig": None})
        return bound.model_copy(update={"issuer_sig": self._mac(bound)})

    def verify(self, cert: Certificate, principal_id: str) -> bool:
        """True iff ``cert`` was issued by this server for ``principal_id``."""
        if not cert.issuer_sig or cert.principal_id != principal_id:
            return False
        return hmac.compare_digest(cert.issuer_sig, self._mac(cert))

    def accept(self, certs: list[Certificate], principal_id: str
               ) -> tuple[list[Certificate], list[str]]:
        """Split caller-presented certificates into (verified, rejected classes)."""
        ok: list[Certificate] = []
        rejected: list[str] = []
        for c in certs:
            if self.verify(c, principal_id):
                ok.append(c)
            else:
                rejected.append(c.action_class)
        return ok, rejected
