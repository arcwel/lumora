"""Shared pytest fixtures.

Points the app at an isolated temp SQLite database *before* importing any app
module (the engine is created at import time from ``DATABASE_URL``), then gives
each test a freshly-created schema for isolation.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

_TMP_DB = pathlib.Path(tempfile.gettempdir()) / "lumora_pytest.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"

import app.models  # noqa: E402,F401  (register models on Base.metadata)
import pytest  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.prompt import Prompt  # noqa: E402


@pytest.fixture
def db_session():
    """Yield a session against a freshly-created schema, dropped afterward."""

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def project(db_session) -> Project:
    """A persisted project with two active prompts."""

    proj = Project(
        name="Acme Brand",
        brand_name="Acme",
        aliases=["AcmeCo"],
        competitors=["Globex"],
    )
    db_session.add(proj)
    db_session.commit()
    db_session.add_all(
        [
            Prompt(project_id=proj.id, text="What is the best widget company?"),
            Prompt(project_id=proj.id, text="Top alternatives to Globex?"),
        ]
    )
    db_session.commit()
    return proj
