"""Snapshot run entity — one scheduled (or manual) monitoring execution."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.answer import Answer
    from app.models.project import Project


class SnapshotStatus(str, enum.Enum):
    """Lifecycle states for a snapshot run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SnapshotRun(TimestampMixin, Base):
    """A single execution that queries providers and judges the answers."""

    __tablename__ = "snapshot_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[SnapshotStatus] = mapped_column(
        Enum(SnapshotStatus, native_enum=False, length=16),
        default=SnapshotStatus.PENDING,
        nullable=False,
    )

    # Provenance: which models produced and judged this run.
    provider_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    judge_prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="snapshot_runs")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="snapshot_run",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<SnapshotRun id={self.id} status={self.status.value}>"
