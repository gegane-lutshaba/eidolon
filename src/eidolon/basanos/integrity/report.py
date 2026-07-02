"""Integrity report + certificate types (PRD §6.6 v2)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from eidolon.profile.schema import AutonomyLevel


class Finding(BaseModel):
    """One adversarial case where the twin was NOT contained (a defect)."""

    model_config = {"frozen": True}

    suite: str
    case: str
    description: str
    observed_level: str  # the (unsafe) KAIROS level the twin reached
    expected_safe: list[str]  # levels that would have been safe


class SuiteResult(BaseModel):
    model_config = {"frozen": True}

    suite: str
    cases_run: int
    cases_contained: int
    findings: list[Finding] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings

    @property
    def score(self) -> float:
        return self.cases_contained / self.cases_run if self.cases_run else 1.0


class IntegrityReport(BaseModel):
    """Aggregate result of running the adversarial suites against a twin."""

    model_config = {"frozen": True}

    profile_id: str
    suites: list[SuiteResult] = Field(default_factory=list)

    @property
    def findings(self) -> list[Finding]:
        return [f for s in self.suites for f in s.findings]

    @property
    def cases_run(self) -> int:
        return sum(s.cases_run for s in self.suites)

    @property
    def cases_contained(self) -> int:
        return sum(s.cases_contained for s in self.suites)

    @property
    def score(self) -> float:
        return self.cases_contained / self.cases_run if self.cases_run else 1.0

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.suites)


class IntegrityCertificate(BaseModel):
    """Certifies a twin's adversarial robustness and the autonomy it supports."""

    model_config = {"frozen": True}

    profile_id: str
    passed: bool
    score: float
    cases_run: int
    # The highest autonomy this certificate is willing to back. A twin that
    # fails any case earns at most ``draft`` (reviewable) — never an unattended
    # acting level.
    ceiling: AutonomyLevel
