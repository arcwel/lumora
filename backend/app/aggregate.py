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
from app.models.snapshot import SnapshotRun, SnapshotStatus


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


@dataclass(slots=True)
class ProviderStat:
    """Mention stats for one provider, collapsed across all of its prompts/models."""

    provider: str
    total_runs: int = 0
    mentions: int = 0
    positions: list[int] = field(default_factory=list)

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


def latest_completed_run(session: Session, project_id: int) -> SnapshotRun | None:
    """Return the most recent *completed* run for a project, or ``None``.

    The dashboard reports rates off finished runs only — a run still RUNNING (or
    one that FAILED before scoring) has no meaningful mention rate.
    """

    return session.scalars(
        select(SnapshotRun)
        .where(
            SnapshotRun.project_id == project_id,
            SnapshotRun.status == SnapshotStatus.COMPLETED,
        )
        .order_by(SnapshotRun.id.desc())
        .limit(1)
    ).first()


def completed_runs(
    session: Session, project_id: int, *, limit: int | None = None
) -> list[SnapshotRun]:
    """Return completed runs for a project, oldest → newest (chart-friendly order).

    ``limit`` caps the result to the most recent N runs (still returned oldest
    first) so trend charts and sparklines stay bounded on busy projects.
    """

    stmt = (
        select(SnapshotRun)
        .where(
            SnapshotRun.project_id == project_id,
            SnapshotRun.status == SnapshotStatus.COMPLETED,
        )
        .order_by(SnapshotRun.id.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    runs = list(session.scalars(stmt).all())
    runs.reverse()
    return runs


def overall_mention_rate(stats: list[GroupStat]) -> float | None:
    """Pool a run's per-group stats into a single mention rate, or ``None``.

    Returns ``None`` when there were no passes at all (so callers can render an
    empty state rather than a misleading 0%).
    """

    total = sum(s.total_runs for s in stats)
    if not total:
        return None
    return sum(s.mentions for s in stats) / total


def summarize_by_provider(stats: list[GroupStat]) -> list[ProviderStat]:
    """Collapse per-(prompt, model) ``GroupStat`` rows into per-provider totals.

    Used for the "which AI mentions you most" comparison: a provider's rate is
    pooled across every prompt and model it answered. Sorted by provider name.
    """

    providers: dict[str, ProviderStat] = {}
    for stat in stats:
        ps = providers.get(stat.provider)
        if ps is None:
            ps = ProviderStat(provider=stat.provider)
            providers[stat.provider] = ps
        ps.total_runs += stat.total_runs
        ps.mentions += stat.mentions
        ps.positions.extend(stat.positions)
    return sorted(providers.values(), key=lambda p: p.provider)


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
