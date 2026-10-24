"""Hierarchical path scopes (known-issue #7)."""

from __future__ import annotations

import pytest

from eidolon.common import crypto
from eidolon.common.errors import AttenuationError
from eidolon.sage.port import Scope
from eidolon.themis import Themis
from eidolon.themis.scope import meet, normalize_path, path_within
from eidolon.themis.types import MintParams
from eidolon.types import Action


@pytest.mark.parametrize("child,parent,ok", [
    ("src/a.py", "src", True),
    ("src", "src", True),
    ("src/billing/x.py", "src/billing", True),
    ("srcx/a.py", "src", False),          # prefix of the name, not the path
    ("src/../etc/passwd", "src", False),  # escapes the grant
    ("../etc", ".", False),               # escapes the workspace
    ("./src//a.py", "src", True),         # normalised
    ("src\\win\\a.py", "src", True),
    ("/repo/src/a.py", "/repo/src", True),
    ("/repo/src/../../etc", "/repo", False),
    ("src/a.py", "/repo/src", False),     # relative vs absolute never mix
    ("anything/deep", ".", True),
])
def test_path_within(child, parent, ok) -> None:
    assert path_within(child, parent) is ok


def test_normalize_rejects_escape() -> None:
    assert normalize_path("a/../../b") is None
    assert normalize_path("a/./b/") == "a/b"


def test_meet_keeps_the_most_specific() -> None:
    assert meet("path", {"src"}, {"src/billing", "docs"}) == {"src/billing"}
    assert meet("project", {"a", "b"}, {"b", "c"}) == {"b"}


def _mint(themis, principal, twin, path):
    return themis.mint(principal.signing_key_hex, MintParams(
        principal_id=principal.public_key_hex, issued_to=twin.public_key_hex,
        scope={"project": ["atlas"], "path": path}, permitted_classes=["edit-code"],
        max_autonomy="autonomous", blast_radius_budget={"scope_expansion": 0}))


def _edit(path):
    return Action(id="e", action_class="edit-code", description="edit",
                  scope=Scope(selectors={"project": ["atlas"], "path": [path]}))


def test_grant_on_a_directory_authorizes_files_under_it() -> None:
    themis, p, t = Themis(), crypto.generate_keypair(), crypto.generate_keypair()
    root = _mint(themis, p, t, ["src"])
    assert themis.verify(_edit("src/billing/invoice.py"), [root], p.public_key_hex).valid
    denied = themis.verify(_edit("infra/prod.tf"), [root], p.public_key_hex)
    assert not denied.valid and "path" in denied.reason
    assert not themis.verify(_edit("src/../infra/prod.tf"), [root], p.public_key_hex).valid


def test_attenuate_a_directory_to_a_subdirectory() -> None:
    themis = Themis()
    p, t, sub = (crypto.generate_keypair() for _ in range(3))
    root = _mint(themis, p, t, ["src"])
    child = themis.attenuate(root, MintParams(
        principal_id=p.public_key_hex, issued_to=sub.public_key_hex,
        scope={"project": ["atlas"], "path": ["src/billing"]}, permitted_classes=["edit-code"],
        max_autonomy="autonomous", blast_radius_budget={"scope_expansion": 0}), t.signing_key_hex)
    chain = [root, child]
    assert themis.verify(_edit("src/billing/a.py"), chain, p.public_key_hex).valid
    # the sub-agent lost the rest of src
    assert not themis.verify(_edit("src/auth/a.py"), chain, p.public_key_hex).valid


def test_attenuation_can_never_widen_a_path() -> None:
    themis = Themis()
    p, t, sub = (crypto.generate_keypair() for _ in range(3))
    root = _mint(themis, p, t, ["src/billing"])
    for wider in (["src"], ["."], ["src/billing/../auth"]):
        with pytest.raises(AttenuationError):
            themis.attenuate(root, MintParams(
                principal_id=p.public_key_hex, issued_to=sub.public_key_hex,
                scope={"project": ["atlas"], "path": wider}, permitted_classes=["edit-code"],
                max_autonomy="autonomous", blast_radius_budget={"scope_expansion": 0}),
                t.signing_key_hex)


# -- property: path attenuation never widens -------------------------------
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

_seg = st.sampled_from(["src", "billing", "auth", "docs", "..", ".", "a.py", "x"])
_path = st.lists(_seg, min_size=1, max_size=4).map("/".join)


@settings(max_examples=300, deadline=None)
@given(parent=st.lists(_path, min_size=1, max_size=3),
       child=st.lists(_path, min_size=1, max_size=3),
       probe=_path)
def test_property_child_path_grant_within_parent(parent, child, probe) -> None:
    themis = Themis()
    p, t, sub = (crypto.generate_keypair() for _ in range(3))
    root = _mint(themis, p, t, parent)
    try:
        leaf = themis.attenuate(root, MintParams(
            principal_id=p.public_key_hex, issued_to=sub.public_key_hex,
            scope={"project": ["atlas"], "path": child}, permitted_classes=["edit-code"],
            max_autonomy="autonomous", blast_radius_budget={"scope_expansion": 0}),
            t.signing_key_hex)
    except AttenuationError:
        return
    if themis.verify(_edit(probe), [root, leaf], p.public_key_hex).valid:
        assert themis.verify(_edit(probe), [root], p.public_key_hex).valid
