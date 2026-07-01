# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""SQLAlchemy engine + session factory.

All ORM models bind to ``MetaData(schema=settings.db_schema)`` so DDL +
queries land in the ``surge_quality`` Postgres schema, isolated from the
Brain tables that share the same database.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from surge_quality.settings import get_settings

_settings = get_settings()

# Schema-bound metadata: all tables created via Base land in surge_quality.
_metadata = MetaData(schema=_settings.db_schema)


class Base(DeclarativeBase):
    """Declarative base shared by every model."""

    metadata = _metadata


_engine = create_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def get_engine():
    """Return the process-singleton engine. Test fixtures may override."""
    return _engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Yields a session, ensures close on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
