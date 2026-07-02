"""Integrity runner (PRD §6.6 v2).

Executes adversarial cases against a twin and produces an :class:`IntegrityReport`.
The twin is probed through a minimal :class:`TwinUnderTest` seam so the runner
is decoupled from KAIROS wiring:

    poison(contents)          -> plant hostile memories
    resolve(action, context)  -> the twin's gated decision (level)

:class:`KairosTwinAdapter` builds that seam from a live KAIROS gate + SAGE port.
A case is *contained* when the resolved level is within its ``safe_levels``.
"""

from __future__ import annotations

from typing import Protocol

from eidolon.basanos.integrity.report import Finding, IntegrityReport, SuiteResult
from eidolon.basanos.integrity.suites import AttackCase, all_cases
from eidolon.profile.schema import DomainProfile
from eidolon.types import Action, Context


class TwinUnderTest(Protocol):
    principal_id: str

    def poison(self, contents: list[str]) -> None: ...
    def resolve(self, action: Action, context: Context) -> str: ...  # returns level


class IntegrityRunner:
    def run(
        self,
        twin: TwinUnderTest,
        profile: DomainProfile,
        cases: list[AttackCase] | None = None,
    ) -> IntegrityReport:
        cases = cases if cases is not None else all_cases(profile, twin.principal_id)

        by_suite: dict[str, list[AttackCase]] = {}
        for c in cases:
            by_suite.setdefault(c.suite, []).append(c)

        results: list[SuiteResult] = []
        for suite, suite_cases in sorted(by_suite.items()):
            contained = 0
            findings: list[Finding] = []
            for case in suite_cases:
                if case.poison_memories:
                    twin.poison(case.poison_memories)
                level = twin.resolve(case.action, case.context)
                if level in case.safe_levels:
                    contained += 1
                else:
                    findings.append(
                        Finding(
                            suite=suite,
                            case=case.name,
                            description=case.description,
                            observed_level=level,
                            expected_safe=case.safe_levels,
                        )
                    )
            results.append(
                SuiteResult(
                    suite=suite,
                    cases_run=len(suite_cases),
                    cases_contained=contained,
                    findings=findings,
                )
            )
        return IntegrityReport(profile_id=profile.id, suites=results)


class KairosTwinAdapter:
    """Adapt a wired KAIROS gate + SAGE port into a :class:`TwinUnderTest`.

    The twin under test is fully empowered — a valid chain and fidelity
    certificates granting the mandate's autonomy — so the suites test whether
    hostile inputs can push it BEYOND that mandate, not merely whether it is
    uncertified.
    """

    def __init__(self, kairos, sage, principal_id, chain, certificates) -> None:  # noqa: ANN001
        self._kairos = kairos
        self._sage = sage
        self.principal_id = principal_id
        self._chain = chain
        self._certs = certificates

    def poison(self, contents: list[str]) -> None:
        for c in contents:
            self._sage.observe(self.principal_id, c, "memory", "adversarial.integrity")

    def resolve(self, action: Action, context: Context) -> str:
        decision = self._kairos.resolve(action, context, self._chain, self._certs)
        return decision.level.value
