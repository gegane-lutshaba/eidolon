"""Database engine/session plumbing.

Uses ``create_all`` for dev (migrations deferred). The engine URL comes from
settings; tests may pass an in-memory SQLite URL.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
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

    Base.metadata.create_all(get_engine(url))
