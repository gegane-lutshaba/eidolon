"""Public break-the-gate mode: per-visitor isolation, rate limiting, auto-reset,
and the auth boundary — /challenge* open ONLY under EIDOLON_PUBLIC_CHALLENGE,
with every visitor in their own in-memory world (never the real ledger) and the
rest of the platform still token-gated.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings
from eidolon.showcase.challenge import ChallengeArena

WIRE = {"tool": "wire_funds", "arguments": {"amount": "9", "to_account": "x"}}


# --- arena mechanics (injected clock) -----------------------------------
def _arena(**kw):
    now = {"t": 0.0}
    kw.setdefault("clock", lambda: now["t"])
    return ChallengeArena(**kw), now


def test_sessions_are_isolated() -> None:
    arena, _ = _arena()
    sid_a, a = arena.session(None)
    sid_b, b = arena.session(None)
    assert sid_a != sid_b
    a.call("wire_funds", {"amount": "1"})
    assert len(a.attempts) == 1 and len(b.attempts) == 0  # no cross-talk
    assert a.principal_id != b.principal_id
    # same cookie -> same session back
    sid_a2, a2 = arena.session(sid_a)
    assert sid_a2 == sid_a and a2 is a


def test_idle_ttl_resets_session() -> None:
    arena, now = _arena(ttl_seconds=100)
    sid, ch = arena.session(None)
    ch.call("wire_funds", {"amount": "1"})
    now["t"] = 50
    _, same = arena.session(sid)
    assert same is ch                      # still alive, touched
    now["t"] = 151                          # 101s after the touch
    _, fresh = arena.session(sid)
    assert fresh is not ch and fresh.attempts == []  # auto-reset


def test_lru_eviction_under_session_cap() -> None:
    arena, _ = _arena(max_sessions=3)
    sids = [arena.session(None)[0] for _ in range(4)]
    assert arena.session_count <= 3
    # the oldest was evicted; newest survive
    _, fresh = arena.session(sids[0])
    assert fresh.attempts == []


def test_rate_limit_sliding_window() -> None:
    arena, now = _arena(rate_limit=3, rate_window=60)
    assert all(arena.allow_call("1.2.3.4") for _ in range(3))
    assert not arena.allow_call("1.2.3.4")      # 4th within the window: blocked
    assert arena.allow_call("5.6.7.8")          # other IPs unaffected
    now["t"] = 61
    assert arena.allow_call("1.2.3.4")          # window slid


# --- API behavior --------------------------------------------------------
@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("EIDOLON_PUBLIC_CHALLENGE", "true")
    monkeypatch.setenv("EIDOLON_ADMIN_TOKEN", "admin-t")  # rest of app stays gated
    get_settings.cache_clear()
    import eidolon.api.app as app_module

    app_module._arena = None
    yield app_module
    app_module._arena = None
    get_settings.cache_clear()


def test_public_mode_opens_challenge_only(public) -> None:
    client = TestClient(public.app)
    # /challenge page redirects to VERSUS; the API is what powers the demo
    assert client.get("/challenge", follow_redirects=False).status_code == 307
    assert client.get("/challenge/state").status_code == 200
    r = client.post("/challenge/call", json=WIRE)
    assert r.status_code == 200 and r.json()["blocked"] is True  # the gate still holds
    # the rest of the platform is still token-gated
    assert client.post("/keypair").status_code == 401
    assert client.get("/audit/chain").status_code == 401


def test_public_visitors_are_isolated(public) -> None:
    a, b = TestClient(public.app), TestClient(public.app)
    a.post("/challenge/call", json=WIRE)
    assert len(a.get("/challenge/state").json()["attempts"]) == 1
    assert len(b.get("/challenge/state").json()["attempts"]) == 0
    assert a.get("/challenge/state").json()["public"] is True


def test_public_attacks_never_touch_real_ledger(public) -> None:
    client = TestClient(public.app)
    client.post("/challenge/call", json=WIRE)
    pid = client.get("/challenge/state").json()["principal_id"]
    # the runtime's real SAGE port has no attestation for the visitor principal
    from eidolon.sage.port import ReplayFilter

    assert public.runtime().sage.replay(ReplayFilter(principal_id=pid)) == []


def test_public_reset_only_clears_own_session(public) -> None:
    a, b = TestClient(public.app), TestClient(public.app)
    a.post("/challenge/call", json=WIRE)
    b.post("/challenge/call", json=WIRE)
    a.post("/challenge/reset")
    assert len(a.get("/challenge/state").json()["attempts"]) == 0
    assert len(b.get("/challenge/state").json()["attempts"]) == 1


def test_public_rate_limit_429(public, monkeypatch) -> None:
    from eidolon.showcase.challenge import ChallengeArena

    public._arena = ChallengeArena(rate_limit=2, rate_window=60)
    client = TestClient(public.app)
    assert client.post("/challenge/call", json=WIRE).status_code == 200
    assert client.post("/challenge/call", json=WIRE).status_code == 200
    assert client.post("/challenge/call", json=WIRE).status_code == 429


def test_gated_by_default(monkeypatch) -> None:
    # Without the opt-in, /challenge still requires a token.
    monkeypatch.setenv("EIDOLON_ADMIN_TOKEN", "admin-t")
    monkeypatch.delenv("EIDOLON_PUBLIC_CHALLENGE", raising=False)
    get_settings.cache_clear()
    import eidolon.api.app as app_module

    client = TestClient(app_module.app)
    assert client.get("/challenge/state").status_code == 401
    get_settings.cache_clear()
