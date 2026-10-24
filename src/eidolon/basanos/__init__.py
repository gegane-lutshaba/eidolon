"""BASANOS — certification (PRD §6.6).

Two faces gate the autonomy ceiling:

- **Fidelity** — certify, per capability class, that the twin decides like the
  principal on held-out real decisions (``Basanos.certify_fidelity``).
- **Integrity** — adversarial suites (memory poisoning, injection, scope evasion)
  must all be contained before acting-level autonomy is granted
  (``Basanos.integrity_suite`` / ``certify_integrity``).

Over the HTTP API, certificates are issued server-side and signed by a
:class:`CertificateIssuer`, so callers cannot assert their own ceilings.
"""

from eidolon.basanos.certify import Basanos, Certificate
from eidolon.basanos.integrity import (
    IntegrityCertificate,
    IntegrityReport,
    IntegrityRunner,
    KairosTwinAdapter,
    TwinUnderTest,
)
from eidolon.basanos.issuer import CertificateIssuer

__all__ = [
    "Basanos",
    "Certificate",
    "CertificateIssuer",
    "IntegrityReport",
    "IntegrityCertificate",
    "IntegrityRunner",
    "KairosTwinAdapter",
    "TwinUnderTest",
]
