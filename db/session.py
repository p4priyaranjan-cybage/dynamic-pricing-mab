"""SQLAlchemy engine/session setup.

Defaults to a local SQLite file (zero-config for POC/dev). Set the
DATABASE_URL environment variable to point at Postgres when running the
containerized (podman-compose) stack - the same models/queries work
unmodified against either, per the plan's "clean migration path" design.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

_DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "pricing.db"


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    _DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{_DEFAULT_SQLITE_PATH.as_posix()}"


engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False} if _database_url().startswith("sqlite") else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Session:
    """Return a new SQLAlchemy session. Caller is responsible for closing it."""
    return SessionLocal()


def init_db() -> None:
    """Create all tables if they don't already exist."""
    from db.models import Base  # local import to avoid circular import at module load

    Base.metadata.create_all(bind=engine)
