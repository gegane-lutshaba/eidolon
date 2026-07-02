"""P0.3 acceptance (PRD §5.2, §9):
- general-continuity loads and validates;
- invalid profiles are rejected with descriptive errors.
"""

from __future__ import annotations

import copy

import pytest

from eidolon.common.errors import ProfileInvalid
from eidolon.profile import ProfileLoader
from eidolon.profile.schema import min_autonomy


@pytest.fixture
def loader() -> ProfileLoader:
    return ProfileLoader()


@pytest.fixture
def valid_manifest(loader: ProfileLoader) -> dict:
    # Round-trip the shipped profile back into a manifest dict for mutation.
    profile = loader.load("general-continuity")
    return {"domain_profile": profile.model_dump(by_alias=True, mode="json")}


def test_general_continuity_loads(loader: ProfileLoader) -> None:
    profile = loader.load("general-continuity")
    assert profile.id == "general-continuity"
    assert profile.version == "1.0.0"
    assert "commit-action" in profile.class_names()
    assert profile.always_escalates("commit-action")
    assert profile.default_ceiling("answer-status") == "autonomous"
    assert profile.tool_for("post-status") == "chat.post"


def test_version_pin_mismatch_rejected(loader: ProfileLoader) -> None:
    with pytest.raises(ProfileInvalid):
        loader.load("general-continuity", version="9.9.9")


def test_escalation_required_must_exist(loader, valid_manifest) -> None:
    m = copy.deepcopy(valid_manifest)
    m["domain_profile"]["mandate_schema"]["escalation_required"] = ["ghost-class"]
    result = ProfileLoader.validate(m)
    assert not result.ok
    assert any("ghost-class" in e for e in result.errors)


def test_tool_binding_must_exist(loader, valid_manifest) -> None:
    m = copy.deepcopy(valid_manifest)
    m["domain_profile"]["tool_bindings"].append(
        {"class": "nonexistent", "mcp_tool_ref": "x.y"}
    )
    result = ProfileLoader.validate(m)
    assert not result.ok
    assert any("nonexistent" in e for e in result.errors)


def test_irreversible_ceiling_capped_at_draft(loader, valid_manifest) -> None:
    m = copy.deepcopy(valid_manifest)
    for cap in m["domain_profile"]["capability_taxonomy"]:
        if cap["class"] == "commit-action":
            cap["default_autonomy_ceiling"] = "autonomous"  # illegal: irreversible
    result = ProfileLoader.validate(m)
    assert not result.ok
    assert any("commit-action" in e and "draft" in e for e in result.errors)


def test_min_autonomy_ordering() -> None:
    assert min_autonomy("autonomous", "draft", "notify") == "draft"
    assert min_autonomy("observe", "autonomous") == "observe"
