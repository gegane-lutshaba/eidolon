"""Evidence grounding for the judgment engine (inspectable).

The judgment engine must stay auditable: no black-box model may produce a
``decision``. So grounding here only computes *relevance scores* between an
action and recalled memories — the same role semantic recall already plays — and
the decision policy remains a transparent threshold over those scores.

Two relevance signals, both numeric and inspectable:
- **Lexical Dice** over normalized (lightly stemmed) tokens, so ``get_balance``
  grounds against "the user reads balances" without brittle exact matches.
- Optional **embedding cosine** via a pluggable :class:`Embedder`. The default
  :class:`HashingEmbedder` is deterministic and offline (a hashed bag-of-words),
  so grounding is reproducible with no external dependency; production may inject
  SAGE's embeddings instead.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

_SPLIT = re.compile(r"[^a-z0-9]+")
_STOP = {"the", "and", "for", "with", "that", "this", "you", "your", "from", "not",
         "will", "any", "are", "was", "has", "have", "per", "via", "each", "all"}


def normalize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords, light-stem."""
    out: list[str] = []
    for raw in _SPLIT.split(text.lower()):
        if len(raw) < 3 or raw in _STOP:
            continue
        out.append(_stem(raw))
    return out


def _stem(w: str) -> str:
    """Collapse only the plural / 3rd-person-singular 's' (and 'ies'→'y').

    Deliberately conservative: aggressive suffix stripping (``es``/``ing``/``ed``)
    causes false *mismatches* (``balances``→``balanc`` vs ``balance``). Handling
    just the trailing ``s`` catches the dominant surface variation
    (reads/emails/balances/reserves/summarizes) without breaking stems.
    """
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ss"):
        return w
    if w.endswith("s") and len(w) > 3:
        return w[:-1]
    return w


def dice(a: set[str], b: set[str]) -> float:
    """Sørensen–Dice coefficient in [0, 1]."""
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic, offline bag-of-words hashing embedder (no dependencies).

    Not a learned model — a reproducible feature map. Each normalized token is
    hashed into one of ``dim`` buckets; the vector is L2-normalized so cosine is
    a bounded, inspectable similarity. Good enough to make grounding robust to
    surface variation without pulling in a heavy embedding stack.
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for tok in normalize(text):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            vec[h % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return max(0.0, min(1.0, dot))  # both L2-normalized → dot is cosine in [0,1]


def relevance(query: str, content: str, embedder: Embedder | None = None) -> float:
    """Blended relevance in [0, 1]: lexical Dice, optionally averaged with cosine."""
    lex = dice(set(normalize(query)), set(normalize(content)))
    if embedder is None:
        return lex
    cos = cosine(embedder.embed(query), embedder.embed(content))
    return 0.5 * lex + 0.5 * cos
