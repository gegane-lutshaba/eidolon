"""Property tests for the LOCKED invariants (PRD §0, §8):
- attenuation never widens authority on ANY dimension;
- default-deny: a verified child's effective authority is always ⊆ its parent's.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from eidolon.common import crypto
from eidolon.common.errors import AttenuationError
from eidolon.profile.schema import AUTONOMY_ORDER, autonomy_rank
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window

CLASSES = ["answer-status", "retrieve-context", "draft-comm", "post-status", "commit-action"]
EXCLUSIONS = ["financial-commitment", "external-client-comm", "personnel-decision", "legal-commitment"]
PROJECTS = ["atlas", "borealis", "carina", "draco"]


def _subset_strategy(items):
    return st.lists(st.sampled_from(items), unique=True).map(sorted)


scope_st = st.dictionaries(
    keys=st.sampled_from(["project", "channel"]),
    values=_subset_strategy(PROJECTS),
    max_size=2,
)

mint_over = st.fixed_dictionaries(
    {
        "scope": scope_st,
        "permitted_classes": _subset_strategy(CLASSES),
        "exclusions": _subset_strategy(EXCLUSIONS),
        "escalation_required": _subset_strategy(CLASSES),
        "max_autonomy": st.sampled_from(AUTONOMY_ORDER),
        "posts": st.integers(min_value=0, max_value=20),
    }
)


@settings(max_examples=200, deadline=None)
@given(parent_o=mint_over, child_o=mint_over)
def test_attenuation_never_widens(parent_o, child_o) -> None:
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    sub = crypto.generate_keypair()
    themis = Themis()

    root = themis.mint(
        principal.signing_key_hex,
        MintParams(
            principal_id=principal.public_key_hex,
            issued_to=twin.public_key_hex,
            scope=parent_o["scope"],
            permitted_classes=parent_o["permitted_classes"],
            exclusions=parent_o["exclusions"],
            escalation_required=parent_o["escalation_required"],
            max_autonomy=parent_o["max_autonomy"],
            blast_radius_budget={"posts_per_window": parent_o["posts"], "scope_expansion": 0},
            window=Window(),
            revocation=Revocation(),
            nonce="root",
        ),
    )
    child_params = MintParams(
        principal_id=principal.public_key_hex,
        issued_to=sub.public_key_hex,
        scope=child_o["scope"],
        permitted_classes=child_o["permitted_classes"],
        exclusions=child_o["exclusions"],
        escalation_required=child_o["escalation_required"],
        max_autonomy=child_o["max_autonomy"],
        blast_radius_budget={"posts_per_window": child_o["posts"], "scope_expansion": 0},
        window=Window(),
        revocation=Revocation(),
        nonce="child",
    )

    # Determine whether the child is a true subset on every dimension.
    def scope_subset() -> bool:
        for stype, vals in child_o["scope"].items():
            if not set(vals).issubset(parent_o["scope"].get(stype, [])):
                return False
        return True

    is_subset = (
        scope_subset()
        and set(child_o["permitted_classes"]).issubset(parent_o["permitted_classes"])
        and set(parent_o["exclusions"]).issubset(child_o["exclusions"])
        and set(parent_o["escalation_required"]).issubset(child_o["escalation_required"])
        and autonomy_rank(child_o["max_autonomy"]) <= autonomy_rank(parent_o["max_autonomy"])
        and child_o["posts"] <= parent_o["posts"]
    )

    if is_subset:
        child = themis.attenuate(root, child_params, twin.signing_key_hex)
        res = themis.verify(None, [root, child])
        assert res.valid, res.reason
        eff = res.effective
        # Effective authority is never broader than the parent on any axis.
        assert set(eff.permitted_classes).issubset(parent_o["permitted_classes"])
        assert set(parent_o["exclusions"]).issubset(eff.exclusions)
        assert autonomy_rank(eff.max_autonomy) <= autonomy_rank(parent_o["max_autonomy"])
        assert eff.blast_radius_budget.get("posts_per_window", 0) <= parent_o["posts"]
    else:
        # Any widening must be rejected at attenuation time.
        try:
            themis.attenuate(root, child_params, twin.signing_key_hex)
        except AttenuationError:
            return
        raise AssertionError("widening child was not rejected")
