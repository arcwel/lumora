"""Project / Brand entity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.prompt import Prompt
    from app.models.snapshot import SnapshotRun


class Project(TimestampMixin, Base):
    """A brand being monitored for AI assistant visibility."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # JSON columns are portable across SQLite and Postgres (JSONB-friendly).
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    competitors: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    monthly_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    prompts: Mapped[list["Prompt"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    snapshot_runs: Mapped[list["SnapshotRun"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Project id={self.id} brand={self.brand_name!r}>"
