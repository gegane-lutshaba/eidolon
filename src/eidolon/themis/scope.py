"""Scope-selector semantics.

Most selectors (``project``, ``channel``, ``host``…) are exact-value sets. Path
selectors — ``path`` and any ``*_path`` — are hierarchical: a grant of ``src``
covers ``src/a.py`` and may be attenuated to ``src/billing``. Paths are
normalised (``\\`` → ``/``, ``.``/``..`` collapsed) before comparison, and a path
that escapes upward (``src/../../etc``) or mixes absolute/relative forms is never
covered. THEMIS compares strings; a caller that can see the real filesystem
should pass ``os.path.realpath`` values so a symlink can't smuggle a path out of
its grant.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable


def is_path_selector(selector: str) -> bool:
    return selector == "path" or selector.endswith("_path")


def normalize_path(value: str) -> str | None:
    """Canonical form, or None if the path escapes above its starting point."""
    s = str(value).replace("\\", "/").strip()
    if not s:
        return None
    absolute = s.startswith("/")
    n = posixpath.normpath(s)
    if n.startswith("//"):
        n = "/" + n.lstrip("/")
    if not absolute and (n == ".." or n.startswith("../")):
        return None
    return "." if n == "." else n


def path_within(child: str, parent: str) -> bool:
    c, p = normalize_path(child), normalize_path(parent)
    if c is None or p is None:
        return False
    if c.startswith("/") != p.startswith("/"):
        return False
    if p in (".", "/"):
        return True
    return c == p or c.startswith(p + "/")


def covered(selector: str, value: str, allowed: Iterable[str]) -> bool:
    """Is ``value`` within the granted ``allowed`` values for ``selector``?"""
    if is_path_selector(selector):
        return any(path_within(value, a) for a in allowed)
    return value in set(allowed)


def all_covered(selector: str, values: Iterable[str], allowed: Iterable[str]) -> bool:
    allowed = list(allowed)
    return all(covered(selector, v, allowed) for v in values)


def meet(selector: str, a: Iterable[str], b: Iterable[str]) -> set[str]:
    """Intersection of two grants. For paths, the most specific values both
    allow (``{src}`` ∧ ``{src/billing, docs}`` = ``{src/billing}``)."""
    a, b = set(a), set(b)
    if not is_path_selector(selector):
        return a & b
    return {v for v in a if covered(selector, v, b)} | {v for v in b if covered(selector, v, a)}
