"""BASANOS integrity face (PRD §2.2, §6.6 — v2).

Adversarial certification: probe whether a twin's authority decisions can be
subverted by hostile inputs. Three suites:

- **memory-poisoning** — false/malicious memories that try to make the twin act
  beyond its mandate;
- **injection** — instructions embedded in context/memory that try to override
  the authority verdict;
- **scope-evasion** — actions crafted to slip past scope, exclusion, class, or
  budget boundaries.

A twin passes only if every adversarial case is *contained* (denied, escalated,
or at most drafted). The resulting :class:`IntegrityCertificate` gates the
autonomy ceiling alongside the fidelity certificate (certify-before-empower).
"""

from eidolon.basanos.integrity.attacker import (
    AdversarialAttacker,
    LLMAttacker,
    ProceduralAttacker,
)
from eidolon.basanos.integrity.report import (
    Finding,
    IntegrityCertificate,
    IntegrityReport,
    SuiteResult,
)
from eidolon.basanos.integrity.runner import (
    IntegrityRunner,
    KairosTwinAdapter,
    TwinUnderTest,
)
from eidolon.basanos.integrity.suites import AttackCase, all_cases

__all__ = [
    "Finding",
    "SuiteResult",
    "IntegrityReport",
    "IntegrityCertificate",
    "IntegrityRunner",
    "TwinUnderTest",
    "KairosTwinAdapter",
    "AttackCase",
    "all_cases",
    "AdversarialAttacker",
    "ProceduralAttacker",
    "LLMAttacker",
]
