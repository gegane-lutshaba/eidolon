"""Durable, shared state without Postgres (known-issues #5, #6): revocations +
heartbeats in a local state file, and windowed budgets."""

from __future__ import annotations

import datetime as _dt

import pytest

from eidolon.common import crypto
from eidolon.common.state_db import StateDB
from eidolon.gateway.config import GatewayConfig, build_engine
from eidolon.gateway.mapping import ToolPolicy
from eidolon.kairos.types import BudgetLedger, PostgresBudgetLedger, SqliteBudgetLedger
from eidolon.sage import InMemorySagePort
from eidolon.sage.port import Scope
from eidolon.themis import Themis
from eidolon.themis.revocation_store import SqliteRevocationStore
from eidolon.themis.types import MintParams
from eidolon.types import Action


class Clock:
    def __init__(self) -> None:
        self.now = _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)

    def __call__(self) -> _dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += _dt.timedelta(seconds=seconds)


# -- budgets ------------------------------------------------------------
@pytest.mark.parametrize("make", ["memory", "sqlite", "postgres"])
def test_window_dimensions_reset_and_lifetime_ones_dont(make, tmp_path) -> None:
    clock = Clock()
    if make == "memory":
        ledger: BudgetLedger = BudgetLedger(window_seconds=60, clock=clock)
    elif make == "sqlite":
        ledger = SqliteBudgetLedger(tmp_path / "state.db", window_seconds=60, clock=clock)
    else:
        from eidolon.data.db import get_sessionmaker, init_db

        url = f"sqlite:///{tmp_path/'ops.db'}"
        init_db(url)
        ledger = PostgresBudgetLedger(window_seconds=60, clock=clock,
                                      session_factory=get_sessionmaker(url))
    limits = {"posts_per_window": 2, "deploys": 1}
    ledger.consume("p", {"posts_per_window": 2, "deploys": 1})
    assert ledger.would_exceed("p", {"posts_per_window": 1}, limits) == "posts_per_window"
    assert ledger.would_exceed("p", {"deploys": 1}, limits) == "deploys"
    clock.advance(61)
    assert ledger.would_exceed("p", {"posts_per_window": 1}, limits) is None  # window rolled
    assert ledger.would_exceed("p", {"deploys": 1}, limits) == "deploys"       # lifetime


def test_sqlite_budget_survives_restart(tmp_path) -> None:
    path = tmp_path / "state.db"
    SqliteBudgetLedger(path).consume("p", {"egress_per_window": 3})
    assert SqliteBudgetLedger(path).consumed("p", "egress_per_window") == 3


# -- revocations -------------------------------------------------------
def _root(themis, principal):
    return themis.mint(principal.signing_key_hex, MintParams(
        principal_id=principal.public_key_hex, issued_to=crypto.generate_keypair().public_key_hex,
        scope={"project": ["x"]}, permitted_classes=["answer-status"], max_autonomy="autonomous",
        blast_radius_budget={"scope_expansion": 0}))


def test_revocation_in_one_process_reaches_another(tmp_path) -> None:
    path = tmp_path / "state.db"
    platform = Themis(store=SqliteRevocationStore(path))   # e.g. the platform server
    gateway = Themis(store=SqliteRevocationStore(path))    # e.g. an embedded gate
    p = crypto.generate_keypair()
    root = _root(platform, p)
    action = Action(id="a", action_class="answer-status", description="status",
                    scope=Scope(selectors={"project": ["x"]}))
    assert gateway.verify(action, [root], p.public_key_hex).valid
    platform.revoke(root.id)
    result = gateway.verify(action, [root], p.public_key_hex)
    assert not result.valid and "revoked" in result.reason


def test_revocation_and_heartbeat_survive_restart(tmp_path) -> None:
    path, clock = tmp_path / "state.db", Clock()
    store = SqliteRevocationStore(path, heartbeat_ttl_seconds=10, clock=clock)
    store.revoke("d1")
    store.heartbeat("alice")
    clock.advance(11)
    reopened = SqliteRevocationStore(StateDB(path), heartbeat_ttl_seconds=10, clock=clock)
    assert reopened.is_revoked("d1")
    assert reopened.is_dead_mans_expired("alice")
    assert not reopened.is_dead_mans_expired("never-beat")


# -- wired through the gate --------------------------------------------
def test_gateway_budget_window_end_to_end(tmp_path) -> None:
    key = crypto.generate_keypair()
    cfg = GatewayConfig(
        profile_id="general-continuity", principal_signing_key=key.signing_key_hex,
        scope={"project": ["ops"]}, budget={"posts_per_window": 1, "scope_expansion": 0},
        seed_memories=["the operator will post status page updates during incidents"] * 6,
        tool_policies=[ToolPolicy(tool="post_status_page", action_class="post-status",
                                  scope=Scope(selectors={"project": ["ops"]}),
                                  budget_cost={"posts_per_window": 1})],
        state_path=str(tmp_path / "state.db"), budget_window_seconds=3600,
    )
    engine = build_engine(cfg, sage=InMemorySagePort())
    assert engine.decide("post_status_page", {"message": "investigating"}).allowed
    assert not engine.decide("post_status_page", {"message": "still investigating"}).allowed
    # a restarted gateway on the same state file still remembers the spend
    again = build_engine(cfg, sage=InMemorySagePort())
    assert not again.decide("post_status_page", {"message": "resolved"}).allowed


def test_runtime_uses_the_state_file(monkeypatch, tmp_path) -> None:
    from eidolon.config import Settings
    from eidolon.runtime import build_runtime

    s = Settings(sage_backend="memory", state_path=str(tmp_path / "rt.db"))
    rt = build_runtime(settings=s)
    assert isinstance(rt.budget, SqliteBudgetLedger)
    assert isinstance(rt.themis.store, SqliteRevocationStore)
