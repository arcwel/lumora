"""Read-side aggregation of snapshot results.

With ``N`` variance passes per prompt × provider, a brand "mention" is no longer
binary: it's a rate (e.g. mentioned in 2/3 runs = 67%). These helpers collapse
the raw ``Answer``/``Score`` rows of a run into per-(prompt, provider) summaries
for the CLI ``status`` command and any dashboard view.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.prompt import Prompt
from app.models.score import Score
from app.models.snapshot import SnapshotRun


@dataclass(slots=True)
class GroupStat:
    """Aggregated mention stats for one prompt under one provider/model."""

    prompt_id: int
    prompt_text: str
    provider: str
    model: str
    total_runs: int = 0
    mentions: int = 0
    positions: list[int] = field(default_factory=list)
    sentiments: list[str] = field(default_factory=list)

    @property
    def mention_rate(self) -> float:
        """Fraction of passes that mentioned the brand (0.0–1.0)."""

        return self.mentions / self.total_runs if self.total_runs else 0.0

    @property
    def avg_position(self) -> float | None:
        """Mean 1-based mention rank across passes that mentioned the brand."""

        return sum(self.positions) / len(self.positions) if self.positions else None


def latest_run(session: Session, project_id: int) -> SnapshotRun | None:
    """Return the most recent snapshot run for a project, or ``None``."""

    return session.scalars(
        select(SnapshotRun)
        .where(SnapshotRun.project_id == project_id)
        .order_by(SnapshotRun.id.desc())
        .limit(1)
    ).first()


def aggregate_run(session: Session, run_id: int) -> list[GroupStat]:
    """Collapse a run's answers/scores into per-(prompt, model) ``GroupStat`` rows.

    Sorted by prompt id then model so output is stable across calls.
    """

    rows = session.execute(
        select(Answer, Score, Prompt)
        .join(Prompt, Prompt.id == Answer.prompt_id)
        .outerjoin(Score, Score.answer_id == Answer.id)
        .where(Answer.snapshot_run_id == run_id)
        .order_by(Answer.prompt_id, Answer.model, Answer.run_index)
    ).all()

    groups: dict[tuple[int, str], GroupStat] = {}
    for answer, score, prompt in rows:
        key = (answer.prompt_id, answer.model)
        stat = groups.get(key)
        if stat is None:
            stat = GroupStat(
                prompt_id=answer.prompt_id,
                prompt_text=prompt.text,
                provider=answer.provider,
                model=answer.model,
            )
            groups[key] = stat
        stat.total_runs += 1
        if score is not None and score.brand_mentioned:
            stat.mentions += 1
            if score.mention_position is not None:
                stat.positions.append(score.mention_position)
            if score.sentiment is not None:
                stat.sentiments.append(score.sentiment.value)

    return sorted(groups.values(), key=lambda s: (s.prompt_id, s.model))
