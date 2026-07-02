"""ETHOS snapshot/versioning acceptance (PRD §6.2, §P0.2.1): two versions diffable."""

from __future__ import annotations

from eidolon.ethos.versioning import diff_snapshots, snapshot


def test_snapshot_is_deterministic() -> None:
    a = snapshot({"engine": "JudgmentEngine", "version": "v0"}, profile_id="general-continuity")
    b = snapshot({"engine": "JudgmentEngine", "version": "v0"}, profile_id="general-continuity")
    assert a.version == b.version


def test_two_versions_diffable() -> None:
    a = snapshot({"engine": "JudgmentEngine", "version": "v0"})
    b = snapshot({"engine": "JudgmentEngine", "version": "v1", "threshold": 0.8})
    assert a.version != b.version
    d = diff_snapshots(a, b)
    assert d["version_from"] == a.version
    assert d["version_to"] == b.version
    assert "judgment_policy" in d["changed"]
