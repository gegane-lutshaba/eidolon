"""Operator CLI: verify the persisted attestation ledger is intact.

    python -m eidolon.sage.verify

Recomputes the whole hash chain of the Postgres-backed ledger and reports the
first tampered/broken entry, if any. Exit code 0 = intact, 1 = broken, 2 =
unsupported backend. Wired as ``make deploy-verify``.
"""

from __future__ import annotations

import sys

from eidolon.config import get_settings
from eidolon.sage import get_sage


def main() -> int:
    settings = get_settings()
    if settings.sage_backend != "postgres":
        print(
            f"chain verification applies to the postgres backend; "
            f"EIDOLON_SAGE_BACKEND is '{settings.sage_backend}'.",
            file=sys.stderr,
        )
        return 2

    port = get_sage()
    status = port.verify_chain()  # type: ignore[attr-defined]
    if status.ok:
        print(f"OK — attestation ledger intact ({status.length} entries, hash chain unbroken).")
        return 0
    print(
        f"TAMPERED — hash chain broken at seq={status.broken_at} "
        f"(of {status.length} entries). The ledger has been edited, deleted, or reordered.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
