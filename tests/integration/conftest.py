"""Integration fixtures — bind the live SAGE node (PRD §6.1 acceptance).

These tests run only with a reachable SAGE node and the SDK installed. Bring the
node up with ``make up`` and run ``make test-integration``. If SAGE is not
reachable, the whole module is skipped (so ``make test`` stays green offline).
"""

from __future__ import annotations

import os

import httpx
import pytest

from eidolon.config import Settings
from eidolon.sage.port import SagePort

SAGE_URL = os.environ.get("EIDOLON_SAGE_BASE_URL", "http://localhost:8080")


def _sage_reachable() -> bool:
    for path in ("/health", "/"):
        try:
            r = httpx.get(SAGE_URL + path, timeout=2.0)
            if r.status_code < 500:
                return True
        except Exception:
            continue
    return False


@pytest.fixture(scope="module")
def live_sage() -> SagePort:
    if not _sage_reachable():
        pytest.skip(f"live SAGE not reachable at {SAGE_URL}")
    try:
        from eidolon.sage.client_adapter import SageClientAdapter
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"SAGE SDK unavailable: {exc}")

    settings = Settings(sage_backend="sage", sage_base_url=SAGE_URL)
    try:
        return SageClientAdapter.from_settings(settings)
    except Exception as exc:
        pytest.skip(f"could not construct SageClientAdapter: {exc}")
