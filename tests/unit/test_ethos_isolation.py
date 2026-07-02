"""§6.2 acceptance — style/judgment isolation (a SECURITY boundary).

Two independent proofs:
1. **Structural (import-graph).** No module under ``eidolon.ethos.judgment``
   imports ``eidolon.ethos.style`` (directly or transitively within ethos).
2. **Behavioral.** Removing the style engine entirely changes zero
   ``decision``/``confidence`` outputs.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from eidolon.ethos.facade import Ethos
from eidolon.ethos.style import ClaudeStyleEngine
from eidolon.profile import ProfileLoader
from eidolon.sage import InMemorySagePort
from eidolon.types import Action, Context

JUDGMENT_DIR = pathlib.Path(__file__).resolve().parents[2] / "src/eidolon/ethos/judgment"


def _imports(pyfile: pathlib.Path) -> set[str]:
    tree = ast.parse(pyfile.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_judgment_never_imports_style() -> None:
    offenders = {}
    for pyfile in JUDGMENT_DIR.rglob("*.py"):
        bad = {i for i in _imports(pyfile) if "ethos.style" in i}
        if bad:
            offenders[str(pyfile)] = bad
    assert not offenders, f"judgment engine imports style: {offenders}"


@pytest.fixture
def profile():
    return ProfileLoader().load("general-continuity")


def _seed(sage: InMemorySagePort, principal: str) -> None:
    for text in [
        "principal answers project atlas status questions routinely every week",
        "atlas status is on track for the friday launch per standup notes",
        "principal frequently reports atlas progress to the team",
    ]:
        sage.observe(principal, text, "memory", "docs.read")


def test_removing_style_changes_no_decision(profile) -> None:
    principal = "principal-A"
    action = Action(
        id="a1",
        action_class="answer-status",
        description="answer atlas status question for the team",
    )
    context = Context(principal_id=principal, query="atlas status friday launch")

    sage_with = InMemorySagePort()
    _seed(sage_with, principal)
    ethos_with = Ethos(sage_with, style=ClaudeStyleEngine(), profile=profile)

    sage_without = InMemorySagePort()
    _seed(sage_without, principal)
    ethos_without = Ethos(sage_without, style=None, profile=profile)

    j_with = ethos_with.evaluate(action, context, None, profile)
    j_without = ethos_without.evaluate(action, context, None, profile)

    assert j_with.decision == j_without.decision
    assert j_with.confidence == j_without.confidence
    assert j_with.evidence_refs == j_without.evidence_refs


def test_evidence_refs_present_and_resolvable(profile) -> None:
    principal = "principal-A"
    sage = InMemorySagePort()
    _seed(sage, principal)
    ethos = Ethos(sage, style=None, profile=profile)
    action = Action(id="a1", action_class="answer-status", description="atlas status")
    context = Context(principal_id=principal, query="atlas status")
    j = ethos.evaluate(action, context, None, profile)
    assert j.evidence_refs
    # Every evidence ref must resolve to a real memory in this principal's store.
    resolvable = {m.id for m in sage.recall(principal, action.scope, "atlas", k=50)}
    assert set(j.evidence_refs).issubset(resolvable)
