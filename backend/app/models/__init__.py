"""SQLAlchemy ORM models for Lumora.

Importing this package registers every model with ``Base.metadata`` so that
``create_all`` and Alembic autogenerate see the full schema.
"""

from app.models.answer import Answer
from app.models.project import Project
from app.models.prompt import Prompt
from app.models.score import Score
from app.models.snapshot import SnapshotRun, SnapshotStatus

__all__ = [
    "Answer",
    "Project",
    "Prompt",
    "Score",
    "SnapshotRun",
    "SnapshotStatus",
]
