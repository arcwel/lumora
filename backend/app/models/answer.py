"""Raw AI answer captured during a snapshot run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.prompt import Prompt
    from app.models.score import Score
    from app.models.snapshot import SnapshotRun


class Answer(TimestampMixin, Base):
    """The verbatim response returned by a provider for a given prompt."""

    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_run_id: Mapped[int] = mapped_column(
        ForeignKey("snapshot_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    prompt_id: Mapped[int] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 1-based index of the variance pass this answer came from (N=3 runs).
    run_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    snapshot_run: Mapped["SnapshotRun"] = relationship(back_populates="answers")
    prompt: Mapped["Prompt"] = relationship(back_populates="answers")
    score: Mapped["Score | None"] = relationship(
        back_populates="answer",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Answer id={self.id} provider={self.provider!r} model={self.model!r}>"
