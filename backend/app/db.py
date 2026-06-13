"""Database engine, session, and declarative base setup (SQLAlchemy 2.0 style)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from app.config import settings


def _engine_kwargs(database_url: str) -> dict:
    """Return engine kwargs appropriate for the configured backend."""

    # SQLite needs ``check_same_thread=False`` so the APScheduler thread and
    # the FastAPI request threads can share connections.
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns with UTC defaults.

    Uses timezone-aware ``DateTime`` so the schema is portable to Postgres
    (``TIMESTAMP WITH TIME ZONE``) while remaining valid under SQLite.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


def init_db() -> None:
    """Create all tables. Used for the SQLite MVP; production uses Alembic."""

    # Import models so they register with ``Base.metadata`` before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a scoped database session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
