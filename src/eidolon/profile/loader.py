"""Profile loader + invariant checks (PRD §5.2).

    ProfileLoader.load(id, version)   -> validated, immutable DomainProfile
    ProfileLoader.validate(manifest)  -> Result<Ok, [error]>

Invariants the loader MUST enforce (§5.2):
- every ``escalation_required`` class exists in the taxonomy;
- no ``irreversible`` class has a ``default_autonomy_ceiling`` above ``draft``;
- every ``tool_binding`` class exists in the taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from eidolon.common.errors import ProfileInvalid
from eidolon.profile.schema import AUTONOMY_ORDER, DomainProfile, autonomy_rank

PROFILE_DIR = Path(__file__).parent / "profiles"
# "draft" is the highest ceiling an irreversible class may carry (§5.2).
_MAX_IRREVERSIBLE_RANK = autonomy_rank("draft")


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def raise_for_errors(self) -> None:
        if not self.ok:
            raise ProfileInvalid("; ".join(self.errors))


class ProfileLoader:
    """Loads and validates Domain Profile manifests."""

    def __init__(self, profile_dir: Path = PROFILE_DIR) -> None:
        self._dir = profile_dir

    # -- public API -------------------------------------------------------
    @staticmethod
    def validate(manifest: dict[str, Any]) -> ValidationResult:
        """Schema + invariant validation without constructing a live profile."""
        body = manifest.get("domain_profile", manifest)
        try:
            profile = DomainProfile.model_validate(body)
        except ValidationError as exc:
            return ValidationResult(ok=False, errors=[_fmt_pydantic(exc)])

        errors = _check_invariants(profile)
        return ValidationResult(ok=not errors, errors=errors)

    def load(self, id: str, version: str | None = None) -> DomainProfile:
        """Load a profile by id (and optional version) from the profile dir."""
        manifest = self._read_manifest(id, version)
        result = self.validate(manifest)
        result.raise_for_errors()
        body = manifest.get("domain_profile", manifest)
        profile = DomainProfile.model_validate(body)
        if version is not None and profile.version != version:
            raise ProfileInvalid(
                f"requested version {version} but manifest declares {profile.version}"
            )
        return profile

    def load_manifest_dict(self, manifest: dict[str, Any]) -> DomainProfile:
        """Validate + construct directly from an in-memory manifest dict."""
        self.validate(manifest).raise_for_errors()
        return DomainProfile.model_validate(manifest.get("domain_profile", manifest))

    # -- internals --------------------------------------------------------
    def _read_manifest(self, id: str, version: str | None) -> dict[str, Any]:
        # Accept both hyphen and underscore spellings of the id (manifest ids
        # are hyphenated per §5, filenames are typically snake_case).
        stems = {id, id.replace("-", "_")}
        candidates: list[Path] = []
        if version:
            candidates += [self._dir / f"{s}-{version}.yaml" for s in stems]
        for s in stems:
            candidates += [self._dir / f"{s}.yaml", self._dir / f"{s}.yml"]
        for path in candidates:
            if path.exists():
                with path.open("r", encoding="utf-8") as fh:
                    return yaml.safe_load(fh)
        raise ProfileInvalid(f"no profile manifest found for id={id!r} in {self._dir}")


def _check_invariants(profile: DomainProfile) -> list[str]:
    errors: list[str] = []
    classes = profile.class_names()

    for cls in profile.mandate_schema.escalation_required:
        if cls not in classes:
            errors.append(f"escalation_required class {cls!r} not in taxonomy")

    for binding in profile.tool_bindings:
        if binding.class_ not in classes:
            errors.append(f"tool_binding class {binding.class_!r} not in taxonomy")

    for cap in profile.capability_taxonomy:
        if (
            cap.reversibility == "irreversible"
            and autonomy_rank(cap.default_autonomy_ceiling) > _MAX_IRREVERSIBLE_RANK
        ):
            errors.append(
                f"irreversible class {cap.class_!r} has ceiling "
                f"{cap.default_autonomy_ceiling!r} above 'draft' "
                f"(allowed: {AUTONOMY_ORDER[: _MAX_IRREVERSIBLE_RANK + 1]})"
            )

    # Fidelity rubric decision points should be real classes too (defensive).
    for dp in profile.fidelity_rubric.decision_points:
        if dp not in classes:
            errors.append(f"fidelity_rubric decision_point {dp!r} not in taxonomy")

    return errors


def _fmt_pydantic(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"])
        parts.append(f"{loc}: {err['msg']}")
    return "schema error(s): " + "; ".join(parts)
