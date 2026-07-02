"""ETHOS — fidelity core (PRD §6.2, hybrid, LOCKED).

Two hard-isolated engines:

- **Judgment engine** (``ethos.judgment``) — auditable, LLM-free. The *only*
  thing that produces a ``decision``/``confidence``. Grounded in SAGE recall.
- **Style engine** (``ethos.style``) — generative (Claude). Renders voice for
  drafts and escalation messages ONLY. It must never emit or influence a
  decision, confidence, or scope determination.

The isolation is a security boundary (§6.2), enforced structurally: this
package never imports ``ethos.style`` from ``ethos.judgment``. See
``tests/unit/test_ethos_isolation.py``.
"""

from eidolon.ethos.types import Decision, Judgment
from eidolon.ethos.versioning import EthosSnapshot, diff_snapshots, snapshot

__all__ = ["Judgment", "Decision", "snapshot", "diff_snapshots", "EthosSnapshot"]
