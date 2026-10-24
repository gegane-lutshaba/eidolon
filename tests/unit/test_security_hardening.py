"""Known-issues #2 and #3: token-less mode is loopback-only, and principal keys
need not cross HTTP (pre-signed delegations + approvals; server signing switchable).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.common import crypto
from eidolon.config import get_settings
from eidolon.escalation.types import make_approval
from eidolon.themis import Themis
from eidolon.themis.types import MintParams
from eidolon.types import Action


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'sec.db'}")
    monkeypatch.setenv("EIDOLON_STYLE_ENABLED", "false")
    for var in ("EIDOLON_ADMIN_TOKEN", "EIDOLON_AUDIT_TOKEN", "EIDOLON_OPEN_MODE",
                "EIDOLON_ALLOW_SERVER_SIGNING"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as mod

    mod._runtime = None
    mod._escalations = None
    mod._live_sf = None
    yield mod
    mod._runtime = None
    mod._escalations = None
    mod._live_sf = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


REMOTE = ("203.0.113.7", 40000)


# -- #2: open mode ------------------------------------------------------
def test_tokenless_mode_serves_loopback(app_module) -> None:
    local = TestClient(app_module.app)  # peer "testclient" = in-process
    assert local.get("/whoami").json()["role"] == "admin"
    assert local.get("/escalations").status_code == 200


def test_tokenless_mode_refuses_remote_callers(app_module) -> None:
    remote = TestClient(app_module.app, client=REMOTE)
    assert remote.get("/whoami").json()["role"] is None
    r = remote.get("/escalations")
    assert r.status_code == 401
    # gateway ingest is not open to the network either
    ev = {"gateway_id": "g", "tool": "t", "level": "AUTONOMOUS_ACT"}
    assert remote.post("/ingest/events", json=ev).status_code == 401
    # public pages stay public
    assert remote.get("/health").status_code == 200


def test_explicit_open_mode_opens_to_the_network(app_module, monkeypatch) -> None:
    monkeypatch.setenv("EIDOLON_OPEN_MODE", "1")
    get_settings.cache_clear()
    app_module._runtime = None
    remote = TestClient(app_module.app, client=REMOTE)
    assert remote.get("/whoami").json()["role"] == "admin"


def test_x_forwarded_for_cannot_fake_loopback(app_module, monkeypatch) -> None:
    monkeypatch.setenv("EIDOLON_TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()
    remote = TestClient(app_module.app, client=REMOTE)
    r = remote.get("/escalations", headers={"X-Forwarded-For": "127.0.0.1"})
    assert r.status_code == 401


# -- #3: keys stay client-side -------------------------------------------
def _local_root(principal, twin, classes=("commit-action",)):
    return Themis().mint(principal.signing_key_hex, MintParams(
        principal_id=principal.public_key_hex, issued_to=twin.public_key_hex,
        scope={"project": ["atlas"]}, permitted_classes=list(classes),
        escalation_required=["commit-action"], max_autonomy="autonomous",
        blast_radius_budget={"scope_expansion": 0}))


def test_register_a_client_signed_chain(app_module) -> None:
    client = TestClient(app_module.app)
    principal, twin = crypto.generate_keypair(), crypto.generate_keypair()
    root = _local_root(principal, twin)  # signed locally; no key sent
    r = client.post("/delegations/register", json={"chain": [root.model_dump(mode="json")]})
    assert r.status_code == 200, r.text
    assert r.json()["principal_id"] == principal.public_key_hex

    tampered = root.model_dump(mode="json")
    tampered["body"]["max_autonomy"] = "autonomous"
    tampered["body"]["permitted_classes"] = ["commit-action", "post-status"]
    r = client.post("/delegations/register", json={"chain": [tampered]})
    assert r.status_code == 400 and "signature" in r.json()["detail"]


def test_approve_with_a_presigned_approval(app_module) -> None:
    client = TestClient(app_module.app)
    principal, twin = crypto.generate_keypair(), crypto.generate_keypair()
    pid = principal.public_key_hex
    root = _local_root(principal, twin).model_dump(mode="json")
    action = {"id": "a", "action_class": "commit-action", "description": "sign the atlas contract",
              "scope": {"selectors": {"project": ["atlas"]}}}
    esc_id = client.post("/resolve", json={"action": action, "context": {"principal_id": pid},
                                           "chain": [root]}).json()["escalation_id"]
    assert client.get(f"/escalations/{esc_id}").json()["action_digest"]

    # the principal signs locally; only the signature travels
    approval = make_approval(Action.model_validate(action), pid, principal.signing_key_hex)
    r = client.post(f"/escalations/{esc_id}/approve",
                    json={"approval": approval.model_dump(mode="json")})
    assert r.status_code == 200, r.text
    assert r.json()["approved"] == esc_id


def test_presigned_approval_by_someone_else_is_rejected(app_module) -> None:
    client = TestClient(app_module.app)
    principal, twin, mallory = (crypto.generate_keypair() for _ in range(3))
    pid = principal.public_key_hex
    root = _local_root(principal, twin).model_dump(mode="json")
    action = {"id": "a", "action_class": "commit-action", "description": "sign",
              "scope": {"selectors": {"project": ["atlas"]}}}
    esc_id = client.post("/resolve", json={"action": action, "context": {"principal_id": pid},
                                           "chain": [root]}).json()["escalation_id"]
    forged = make_approval(Action.model_validate(action), mallory.public_key_hex,
                           mallory.signing_key_hex).model_copy(update={"approver_id": pid})
    r = client.post(f"/escalations/{esc_id}/approve",
                    json={"approval": forged.model_dump(mode="json")})
    assert r.status_code == 409


def test_server_signing_can_be_switched_off(app_module, monkeypatch) -> None:
    monkeypatch.setenv("EIDOLON_ALLOW_SERVER_SIGNING", "false")
    get_settings.cache_clear()
    app_module._runtime = None
    client = TestClient(app_module.app)
    assert client.post("/keypair").status_code == 403
    p = crypto.generate_keypair()
    params = {"principal_id": p.public_key_hex, "issued_to": p.public_key_hex}
    assert client.post("/delegations/mint",
                       json={"signing_key": p.signing_key_hex, "params": params}).status_code == 403
