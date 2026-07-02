"""BASANOS — certification (PRD §6.6).

v1 ships the *fidelity face* only: certify, per capability class, that the twin
decides like the principal on held-out real decisions, and gate the autonomy
ceiling on that certificate. The *integrity face* (adversarial suites) is v2 —
its seam is stubbed and raises NotImplementedError.
"""

from eidolon.basanos.certify import Basanos, Certificate
from eidolon.basanos.integrity import (
    IntegrityCertificate,
    IntegrityReport,
    IntegrityRunner,
    KairosTwinAdapter,
    TwinUnderTest,
)

__all__ = [
    "Basanos",
    "Certificate",
    "IntegrityReport",
    "IntegrityCertificate",
    "IntegrityRunner",
    "KairosTwinAdapter",
    "TwinUnderTest",
]
