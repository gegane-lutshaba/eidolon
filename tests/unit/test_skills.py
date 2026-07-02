"""Self-generated skills acceptance (PRD §2.2, §12 — v2).

Load-bearing property: skills are SUBORDINATE to ETHOS/THEMIS. A skill learned
under broad authority must yield nothing it isn't currently authorized for when
replayed — every step is re-resolved by KAIROS.

- synthesis captures only authorized acting steps and validates classes;
- the library is principal-isolated;
- replaying a skill re-checks authority per step (can't smuggle authority);
- a step outside the current mandate halts the run (escalate/deny);
- every executed step is attested (replayable).
"""

from __future__ import annotations

import pytest

from eidolon.basanos import Basanos
from eidolon.basanos.certify import Certificate
from eidolon.common import crypto
from eidolon.common.errors import ProfileInvalid
from eidolon.ethos.facade import Ethos
from eidolon.horkos import Horkos
from eidolon.kairos import Kairos
from eidolon.kairos.types import Decision, DecisionLevel
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import ReplayFilter, Scope
from eidolon.skills import SkillExecutor, SkillLibrary, should_synthesize, synthesize
from eidolon.themis import Themis
from eidolon.themis.types import MintParams, Revocation, Window
from eidolon.types import Action, Context


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


def _certs(profile):
    return [
        Certificate(action_class=c, agreement=1.0, calibration=1.0, sample_size=10,
                    ceiling=profile.default_ceiling(c))
        for c in profile.class_names()
    ]


def _wire(profile, sage, permitted_classes=None):
    principal = crypto.generate_keypair()
    twin = crypto.generate_keypair()
    themis = Themis()
    kairos = Kairos(
        themis=themis, ethos=Ethos(sage, style=None, profile=profile),
        basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile,
    )
    root = themis.mint(
        principal.signing_key_hex,
        MintParams(
            principal_id=principal.public_key_hex, issued_to=twin.public_key_hex,
            scope={"project": ["atlas"], "channel": ["#eng"]},
            exclusions=list(profile.mandate_schema.exclusion_types),
            permitted_classes=permitted_classes or list(profile.class_names()),
            escalation_required=["commit-action"], window=Window(),
            blast_radius_budget={"posts_per_window": 5, "scope_expansion": 0},
            max_autonomy="autonomous", revocation=Revocation(), nonce="root",
        ),
    )
    return kairos, principal, root


def _seed(sage, pid):
    for _ in range(5):
        sage.observe(pid, "principal reports atlas status friday on track weekly to the team", "memory", "docs.read")


def _mk_action(cls, desc="do it", scope_vals=("atlas",), budget=None):
    return Action(id="x", action_class=cls, description=desc,
                  scope=Scope(selectors={"project": list(scope_vals)}), budget_cost=budget or {})


def test_should_synthesize_threshold(profile) -> None:
    d = Decision(level=DecisionLevel.AUTONOMOUS_ACT, rationale="")
    session = [(_mk_action("answer-status"), d) for _ in range(3)]
    assert should_synthesize(session, min_steps=3)
    assert not should_synthesize(session[:2], min_steps=3)


def test_synthesis_captures_only_acting_steps(profile) -> None:
    acting = Decision(level=DecisionLevel.NOTIFY_ACT, rationale="", attestation_hash="h1")
    escalated = Decision(level=DecisionLevel.ESCALATE, rationale="")
    session = [
        (_mk_action("answer-status", "check status"), acting),
        (_mk_action("commit-action", "sign contract"), escalated),  # not captured
        (_mk_action("post-status", "post update"), acting),
    ]
    skill = synthesize("weekly update", "answer then post", "p", profile, session)
    assert skill.classes() == ["answer-status", "post-status"]
    assert "commit-action" not in skill.classes()
    assert "h1" in skill.source_refs


def test_synthesis_rejects_unknown_class(profile) -> None:
    d = Decision(level=DecisionLevel.NOTIFY_ACT, rationale="")
    session = [(_mk_action("teleport"), d)]
    with pytest.raises(ProfileInvalid):
        synthesize("bad", "bad", "p", profile, session)


def test_library_is_principal_isolated(profile) -> None:
    sage = InMemorySagePort()
    lib = SkillLibrary(sage)
    d = Decision(level=DecisionLevel.AUTONOMOUS_ACT, rationale="")
    skill_a = synthesize("a-skill", "atlas status recap", "principal-A", profile,
                         [(_mk_action("answer-status", "atlas status recap"), d)])
    lib.save(skill_a)
    # principal B sees none of A's skills
    assert lib.load("principal-B", "atlas status recap") == []
    assert lib.load("principal-A", "atlas status recap")


def test_skill_run_is_subordinate_and_attested(profile) -> None:
    sage = InMemorySagePort()
    kairos, principal, root = _wire(profile, sage)
    pid = principal.public_key_hex
    _seed(sage, pid)
    d = Decision(level=DecisionLevel.AUTONOMOUS_ACT, rationale="")
    skill = synthesize(
        "status recap", "answer atlas status", pid, profile,
        [(_mk_action("answer-status", "answer atlas status friday on track weekly"), d)],
    )
    ctx = Context(principal_id=pid, query="answer atlas status friday on track weekly")
    run = SkillExecutor(kairos).run(skill, ctx, [root], _certs(profile))
    assert run.completed
    assert run.outcomes[0].level == "AUTONOMOUS_ACT"
    # the replayed step was attested (subordinate to KAIROS attest-then-act)
    replayed = sage.replay(ReplayFilter(principal_id=pid))
    assert any(r.action_class == "answer-status" for r in replayed)


def test_skill_cannot_smuggle_authority(profile) -> None:
    # A skill is learned under FULL authority, then replayed under a NARROWER
    # delegation that omits post-status. The post-status step must halt (deny),
    # proving the skill can't smuggle authority it no longer has.
    sage = InMemorySagePort()
    pid_kp = crypto.generate_keypair()
    pid = pid_kp.public_key_hex
    _seed(sage, pid)

    d = Decision(level=DecisionLevel.AUTONOMOUS_ACT, rationale="")
    skill = synthesize(
        "answer then post", "answer then post atlas status", pid, profile,
        [
            (_mk_action("answer-status", "answer atlas status friday on track weekly"), d),
            (_mk_action("post-status", "post atlas status friday on track weekly",
                        budget={"posts_per_window": 1}),
             Decision(level=DecisionLevel.NOTIFY_ACT, rationale="")),
        ],
    )

    # Narrower runtime authority: only answer-status permitted.
    themis = Themis()
    kairos = Kairos(themis=themis, ethos=Ethos(sage, style=None, profile=profile),
                    basanos=Basanos(), horkos=Horkos(sage), sage=sage, profile=profile)
    narrow_root = themis.mint(
        pid_kp.signing_key_hex,
        MintParams(
            principal_id=pid, issued_to=crypto.generate_keypair().public_key_hex,
            scope={"project": ["atlas"]}, exclusions=list(profile.mandate_schema.exclusion_types),
            permitted_classes=["answer-status"],  # post-status NOT granted
            escalation_required=["commit-action"], window=Window(),
            blast_radius_budget={"scope_expansion": 0}, max_autonomy="autonomous",
            revocation=Revocation(), nonce="narrow",
        ),
    )
    ctx = Context(principal_id=pid, query="answer atlas status friday on track weekly")
    run = SkillExecutor(kairos).run(skill, ctx, [narrow_root], _certs(profile))

    assert not run.completed
    assert run.outcomes[0].level == "AUTONOMOUS_ACT"       # answer-status ok
    assert run.outcomes[1].level == "DENY"                 # post-status denied
    assert run.stopped_at == 1
