"""Judge score derived from an answer by the LLM-as-judge pipeline."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.answer import Answer


class Sentiment(str, enum.Enum):
    """Sentiment of the brand mention within an answer."""

    POSITIVE = "pos"
    NEUTRAL = "neu"
    NEGATIVE = "neg"


class Score(TimestampMixin, Base):
    """Structured judgement of how a brand appears in a single answer."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"),
        index=True,
        unique=True,
        nullable=False,
    )

    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 1-based rank of the brand among entities mentioned; null if not mentioned.
    mention_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentiment: Mapped[Sentiment | None] = mapped_column(
        Enum(Sentiment, native_enum=False, length=8),
        nullable=True,
    )
    cited_sources: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Provenance / reproducibility of the judgement.
    judge_model: Mapped[str] = mapped_column(String(128), nullable=False)
    judge_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    answer: Mapped["Answer"] = relationship(back_populates="score")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Score id={self.id} answer_id={self.answer_id} mentioned={self.brand_mentioned}>"
