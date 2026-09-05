"""Database engine/session plumbing.

Uses ``create_all`` for dev (migrations deferred). The engine URL comes from
settings; tests may pass an in-memory SQLite URL.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from eidolon.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    return create_engine(url, future=True)


@lru_cache
def get_sessionmaker(url: str | None = None) -> sessionmaker:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False, future=True)


def init_db(url: str | None = None) -> None:
    # Import models so they register on Base.metadata before create_all.
    from eidolon.data import models  # noqa: F401
    from eidolon.sage import pg_store  # noqa: F401  (SAGE port tables)

    engine = get_engine(url)
    Base.metadata.create_all(engine)
    _ensure_columns(engine)


# Lightweight additive migrations for columns added to EXISTING tables
# (create_all only creates missing tables, never alters). ADD COLUMN is safe +
# online on both SQLite and Postgres. Keyed by table -> {column: DDL type}.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "agents": {"org_id": "VARCHAR"},
}


def _ensure_columns(engine: Engine) -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    for table, cols in _ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for col, ddl in cols.items():
            if col not in have:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
