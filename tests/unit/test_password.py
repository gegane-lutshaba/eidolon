"""Password self-service: change-password while signed in (proving the current
password). Emailed password reset (forgot/reset-by-token, admin reset-link) was
removed — it cannot be self-service without SMTP delivery.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eidolon.config import get_settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOLON_SAGE_BACKEND", "memory")
    monkeypatch.setenv("EIDOLON_DATABASE_URL", f"sqlite:///{tmp_path/'pw.db'}")
    monkeypatch.setenv("EIDOLON_ADMIN_TOKEN", "admin-t")
    get_settings.cache_clear()
    from eidolon.data import db as db_mod

    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()
    import eidolon.api.app as app_module

    app_module._runtime = None
    app_module._live_sf = None
    app_module._login_hits.clear()
    yield TestClient(app_module.app)
    app_module._runtime = None
    app_module._live_sf = None
    get_settings.cache_clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_sessionmaker.cache_clear()


def _signup(client, email="ada@example.com", password="hunter2hunter2"):
    assert client.post("/auth/signup", json={"email": email, "password": password}).status_code == 200


def test_change_password_flow(client) -> None:
    _signup(client)
    # wrong current -> 400
    assert client.post("/auth/change-password",
                       json={"current_password": "nope", "new_password": "brandnew123"}).status_code == 400
    # too short -> 400
    assert client.post("/auth/change-password",
                       json={"current_password": "hunter2hunter2", "new_password": "short"}).status_code == 400
    # correct
    assert client.post("/auth/change-password",
                       json={"current_password": "hunter2hunter2", "new_password": "brandnew123"}).status_code == 200
    # old password no longer works; new one does
    client.post("/auth/logout")
    client.cookies.clear()
    assert client.post("/auth/login", json={"email": "ada@example.com", "password": "hunter2hunter2"}).status_code == 401
    assert client.post("/auth/login", json={"email": "ada@example.com", "password": "brandnew123"}).status_code == 200


def test_change_password_requires_auth(client) -> None:
    assert client.post("/auth/change-password",
                       json={"current_password": "x", "new_password": "yyyyyyyy"}).status_code == 401


def test_reset_endpoints_are_gone(client) -> None:
    # The emailed-reset surface was removed entirely (needs SMTP, not self-service).
    # The routes no longer exist, so none of them succeeds. The former public
    # paths now fall through to default-deny (401); the admin route 404s.
    _signup(client)
    assert client.post("/auth/forgot", json={"email": "ada@example.com"}).status_code == 401
    assert client.post("/auth/reset", json={"token": "rst_x", "new_password": "whatever8"}).status_code == 401
    assert client.get("/reset?token=rst_x").status_code == 401
    assert client.post("/api/admin/reset-link", json={"email": "ada@example.com"},
                       headers={"Authorization": "Bearer admin-t"}).status_code == 404
