"""Machine-check the TLA+ model of the gate with TLC (#12).

Skips gracefully when Java is unavailable or the TLA+ tools can't be fetched
(offline). When it runs, it asserts the correct spec has no invariant violation
and the deliberately-broken spec is caught — so the formal proof is reproducible
and part of the suite.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from pathlib import Path

import pytest

FORMAL = Path(__file__).resolve().parents[2] / "formal"
JAR = FORMAL / "tla2tools.jar"
JAR_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar"

pytestmark = pytest.mark.skipif(shutil.which("java") is None, reason="java not available")


def _ensure_jar() -> bool:
    if JAR.exists():
        return True
    try:
        urllib.request.urlretrieve(JAR_URL, JAR)  # noqa: S310
        return JAR.exists()
    except Exception:
        return False


def _tlc(module: str, cfg: str) -> str:
    return subprocess.run(
        ["java", "-cp", str(JAR), "tlc2.TLC", "-config", cfg, module],
        cwd=FORMAL, capture_output=True, text=True, timeout=180,
    ).stdout


def test_gate_spec_verifies() -> None:
    if not _ensure_jar():
        pytest.skip("could not obtain tla2tools.jar (offline)")
    out = _tlc("EidolonGate.tla", "EidolonGate.cfg")
    assert "No error has been found" in out, out[-1500:]


def test_broken_gate_is_caught() -> None:
    if not _ensure_jar():
        pytest.skip("could not obtain tla2tools.jar (offline)")
    out = _tlc("EidolonGateBroken.tla", "EidolonGateBroken.cfg")
    # Bypassing attest-then-act must be detected by the model checker.
    assert "NoUnattestedAction is violated" in out, out[-1500:]
