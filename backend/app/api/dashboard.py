"""Read-side dashboard API.

These endpoints power the analytics dashboard (Task 10). They are deliberately
read-only and shaped for display: every payload carries pre-aggregated mention
rates so the frontend can render charts and tables without doing math.

Mounted under ``/api`` to keep the display surface distinct from the CRUD
routes in :mod:`app.api.projects` / ``prompts`` / ``snapshots`` (which stay at
``/projects`` and own creation, editing and run-triggering).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.aggregate import (
    GroupStat,
    aggregate_run,
    completed_runs,
    latest_completed_run,
    overall_mention_rate,
    summarize_by_provider,
)
from app.db import get_db
from app.models.answer import Answer
from app.models.project import Project
from app.models.prompt import Prompt
from app.models.score import Score
from app.models.snapshot import SnapshotRun, SnapshotStatus

router = APIRouter(prefix="/api", tags=["dashboard"])


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #
class ProviderRate(BaseModel):
    """A single provider's pooled mention rate within a run."""

    provider: str
    mention_rate: float
    mentions: int
    total_runs: int
    avg_position: float | None


class ProjectSummary(BaseModel):
    """One card on the dashboard home grid."""

    id: int
    name: str
    brand_name: str
    is_active: bool
    n_prompts: int
    latest_run_id: int | None
    latest_run_at: datetime | None
    latest_status: SnapshotStatus | None
    mention_rate: float | None
    # Oldest → newest overall mention rates, for an inline sparkline.
    sparkline: list[float]


class ProjectDetail(BaseModel):
    """Project configuration plus headline metrics for the detail view."""

    id: int
    name: str
    brand_name: str
    aliases: list[str]
    competitors: list[str]
    monthly_token_budget: int | None
    is_active: bool
    cron_schedule: str | None
    n_prompts: int
    n_active_prompts: int
    n_runs: int
    latest_run_id: int | None
    latest_run_at: datetime | None
    mention_rate: float | None
    # Percentage-point change vs the previous completed run (None if no prior).
    mention_rate_change: float | None
    providers: list[ProviderRate]


class RunRef(BaseModel):
    """A point on the trend x-axis."""

    run_id: int
    timestamp: datetime | None


class TrendSeries(BaseModel):
    """One charted line: a provider's mention rate across runs.

    ``points`` is index-aligned to the response's ``runs`` list; a missing value
    (provider absent from that run) is ``None`` so the line can gap cleanly.
    """

    provider: str
    points: list[float | None]


class TrendsResponse(BaseModel):
    runs: list[RunRef]
    series: list[TrendSeries]
    # Echoes the ?prompt_id filter (None = pooled across all prompts).
    prompt_id: int | None


class GroupStatRead(BaseModel):
    """Serialized per-(prompt, model) aggregate for the snapshot detail view."""

    prompt_id: int
    prompt_text: str
    provider: str
    model: str
    total_runs: int
    mentions: int
    mention_rate: float
    avg_position: float | None


class AnswerRead(BaseModel):
    """One captured answer with its judge score, for drill-down."""

    id: int
    prompt_id: int
    prompt_text: str
    provider: str
    model: str
    run_index: int
    token_count: int | None
    raw_response: str
    brand_mentioned: bool | None
    mention_position: int | None
    sentiment: str | None
    cited_sources: list[str]


class SnapshotSummary(BaseModel):
    """A row in the snapshots list."""

    id: int
    status: SnapshotStatus
    started_at: datetime | None
    completed_at: datetime | None
    n_runs: int
    n_answers: int
    mention_rate: float | None


class SnapshotListResponse(BaseModel):
    items: list[SnapshotSummary]
    total: int
    limit: int
    offset: int


class SnapshotDetail(BaseModel):
    id: int
    project_id: int
    status: SnapshotStatus
    started_at: datetime | None
    completed_at: datetime | None
    provider_model: str | None
    judge_model: str | None
    judge_prompt_version: str | None
    n_runs: int
    error: str | None
    mention_rate: float | None
    groups: list[GroupStatRead]
    providers: list[ProviderRate]
    answers: list[AnswerRead]


class PromptPerformance(BaseModel):
    """A prompt with its per-provider mention rates from the latest run."""

    id: int
    text: str
    category: str | None
    is_active: bool
    mention_rate: float | None
    providers: list[ProviderRate]


class PromptPerformanceResponse(BaseModel):
    run_id: int | None
    run_at: datetime | None
    prompts: list[PromptPerformance]


class ComparisonResponse(BaseModel):
    run_id: int | None
    run_at: datetime | None
    providers: list[ProviderRate]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _require_project(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _provider_rate(provider: str, stat) -> ProviderRate:
    return ProviderRate(
        provider=provider,
        mention_rate=stat.mention_rate,
        mentions=stat.mentions,
        total_runs=stat.total_runs,
        avg_position=stat.avg_position,
    )


def _provider_rates(stats: list[GroupStat]) -> list[ProviderRate]:
    return [_provider_rate(p.provider, p) for p in summarize_by_provider(stats)]


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/projects", response_model=list[ProjectSummary])
def list_project_summaries(db: Session = Depends(get_db)) -> list[ProjectSummary]:
    """List every project with its latest mention rate and a trend sparkline."""

    projects = list(db.scalars(select(Project).order_by(Project.id)).all())

    # Per-project active-prompt counts in one grouped query.
    prompt_counts = dict(
        db.execute(
            select(Prompt.project_id, func.count(Prompt.id))
            .where(Prompt.is_active.is_(True))
            .group_by(Prompt.project_id)
        ).all()
    )

    summaries: list[ProjectSummary] = []
    for project in projects:
        runs = completed_runs(db, project.id, limit=12)
        sparkline: list[float] = []
        for run in runs:
            rate = overall_mention_rate(aggregate_run(db, run.id))
            if rate is not None:
                sparkline.append(round(rate, 4))

        latest = runs[-1] if runs else latest_completed_run(db, project.id)
        latest_rate = sparkline[-1] if sparkline else None

        summaries.append(
            ProjectSummary(
                id=project.id,
                name=project.name,
                brand_name=project.brand_name,
                is_active=project.is_active,
                n_prompts=prompt_counts.get(project.id, 0),
                latest_run_id=latest.id if latest else None,
                latest_run_at=(latest.completed_at or latest.started_at) if latest else None,
                latest_status=latest.status if latest else None,
                mention_rate=latest_rate,
                sparkline=sparkline,
            )
        )
    return summaries


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project_detail(project_id: int, db: Session = Depends(get_db)) -> ProjectDetail:
    """Project config plus headline metrics and trend delta for the detail view."""

    project = _require_project(project_id, db)

    n_prompts = db.scalar(
        select(func.count(Prompt.id)).where(Prompt.project_id == project_id)
    )
    n_active = db.scalar(
        select(func.count(Prompt.id)).where(
            Prompt.project_id == project_id, Prompt.is_active.is_(True)
        )
    )
    n_runs = db.scalar(
        select(func.count(SnapshotRun.id)).where(SnapshotRun.project_id == project_id)
    )

    # Last two completed runs → current rate + change.
    recent = completed_runs(db, project_id, limit=2)
    latest = recent[-1] if recent else None
    prev = recent[-2] if len(recent) >= 2 else None

    latest_rate: float | None = None
    providers: list[ProviderRate] = []
    change: float | None = None
    if latest is not None:
        stats = aggregate_run(db, latest.id)
        latest_rate = overall_mention_rate(stats)
        providers = _provider_rates(stats)
        if prev is not None:
            prev_rate = overall_mention_rate(aggregate_run(db, prev.id))
            if latest_rate is not None and prev_rate is not None:
                change = latest_rate - prev_rate

    return ProjectDetail(
        id=project.id,
        name=project.name,
        brand_name=project.brand_name,
        aliases=project.aliases,
        competitors=project.competitors,
        monthly_token_budget=project.monthly_token_budget,
        is_active=project.is_active,
        cron_schedule=project.cron_schedule,
        n_prompts=n_prompts or 0,
        n_active_prompts=n_active or 0,
        n_runs=n_runs or 0,
        latest_run_id=latest.id if latest else None,
        latest_run_at=(latest.completed_at or latest.started_at) if latest else None,
        mention_rate=latest_rate,
        mention_rate_change=change,
        providers=providers,
    )


@router.get("/projects/{project_id}/trends", response_model=TrendsResponse)
def get_trends(
    project_id: int,
    prompt_id: int | None = Query(default=None, description="Restrict to one prompt"),
    limit: int = Query(default=30, ge=1, le=180, description="Most recent N runs"),
    db: Session = Depends(get_db),
) -> TrendsResponse:
    """Mention rate over time, one series per provider.

    Pooled across all prompts by default; pass ``?prompt_id=`` to chart a single
    prompt. Series points are index-aligned to ``runs`` with ``None`` gaps.
    """

    _require_project(project_id, db)

    runs = completed_runs(db, project_id, limit=limit)
    run_refs = [
        RunRef(run_id=run.id, timestamp=run.completed_at or run.started_at) for run in runs
    ]

    # provider -> {run_index: rate}
    provider_points: dict[str, dict[int, float]] = {}
    for idx, run in enumerate(runs):
        stats = aggregate_run(db, run.id)
        if prompt_id is not None:
            stats = [s for s in stats if s.prompt_id == prompt_id]
        for ps in summarize_by_provider(stats):
            provider_points.setdefault(ps.provider, {})[idx] = round(ps.mention_rate, 4)

    series = [
        TrendSeries(
            provider=provider,
            points=[by_idx.get(i) for i in range(len(runs))],
        )
        for provider, by_idx in sorted(provider_points.items())
    ]

    return TrendsResponse(runs=run_refs, series=series, prompt_id=prompt_id)


@router.get("/projects/{project_id}/comparison", response_model=ComparisonResponse)
def get_comparison(project_id: int, db: Session = Depends(get_db)) -> ComparisonResponse:
    """Side-by-side provider comparison for the latest completed run."""

    _require_project(project_id, db)
    latest = latest_completed_run(db, project_id)
    if latest is None:
        return ComparisonResponse(run_id=None, run_at=None, providers=[])

    stats = aggregate_run(db, latest.id)
    return ComparisonResponse(
        run_id=latest.id,
        run_at=latest.completed_at or latest.started_at,
        providers=_provider_rates(stats),
    )


@router.get("/projects/{project_id}/prompts", response_model=PromptPerformanceResponse)
def get_prompt_performance(
    project_id: int, db: Session = Depends(get_db)
) -> PromptPerformanceResponse:
    """Prompts with their latest per-provider mention rates (latest completed run)."""

    _require_project(project_id, db)
    prompts = list(
        db.scalars(
            select(Prompt).where(Prompt.project_id == project_id).order_by(Prompt.id)
        ).all()
    )

    latest = latest_completed_run(db, project_id)
    stats = aggregate_run(db, latest.id) if latest else []
    by_prompt: dict[int, list[GroupStat]] = {}
    for stat in stats:
        by_prompt.setdefault(stat.prompt_id, []).append(stat)

    rows = [
        PromptPerformance(
            id=prompt.id,
            text=prompt.text,
            category=prompt.category,
            is_active=prompt.is_active,
            mention_rate=overall_mention_rate(by_prompt.get(prompt.id, [])),
            providers=_provider_rates(by_prompt.get(prompt.id, [])),
        )
        for prompt in prompts
    ]

    return PromptPerformanceResponse(
        run_id=latest.id if latest else None,
        run_at=(latest.completed_at or latest.started_at) if latest else None,
        prompts=rows,
    )


@router.get("/projects/{project_id}/snapshots", response_model=SnapshotListResponse)
def list_project_snapshots(
    project_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SnapshotListResponse:
    """Paginated list of snapshot runs with status and overall mention rate."""

    _require_project(project_id, db)

    total = db.scalar(
        select(func.count(SnapshotRun.id)).where(SnapshotRun.project_id == project_id)
    )

    runs = list(
        db.scalars(
            select(SnapshotRun)
            .where(SnapshotRun.project_id == project_id)
            .order_by(SnapshotRun.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )

    # Answer counts for this page of runs, in one grouped query.
    run_ids = [run.id for run in runs]
    answer_counts: dict[int, int] = {}
    if run_ids:
        answer_counts = dict(
            db.execute(
                select(Answer.snapshot_run_id, func.count(Answer.id))
                .where(Answer.snapshot_run_id.in_(run_ids))
                .group_by(Answer.snapshot_run_id)
            ).all()
        )

    items = []
    for run in runs:
        # Only completed runs have a meaningful pooled rate.
        rate = (
            overall_mention_rate(aggregate_run(db, run.id))
            if run.status == SnapshotStatus.COMPLETED
            else None
        )
        items.append(
            SnapshotSummary(
                id=run.id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                n_runs=run.n_runs,
                n_answers=answer_counts.get(run.id, 0),
                mention_rate=rate,
            )
        )

    return SnapshotListResponse(items=items, total=total or 0, limit=limit, offset=offset)


@router.get(
    "/projects/{project_id}/snapshots/{run_id}", response_model=SnapshotDetail
)
def get_snapshot_detail(
    project_id: int, run_id: int, db: Session = Depends(get_db)
) -> SnapshotDetail:
    """A single snapshot run with aggregates and every captured answer + score."""

    _require_project(project_id, db)
    run = db.get(SnapshotRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Snapshot run not found")

    stats = aggregate_run(db, run.id)
    groups = [
        GroupStatRead(
            prompt_id=s.prompt_id,
            prompt_text=s.prompt_text,
            provider=s.provider,
            model=s.model,
            total_runs=s.total_runs,
            mentions=s.mentions,
            mention_rate=s.mention_rate,
            avg_position=s.avg_position,
        )
        for s in stats
    ]

    rows = db.execute(
        select(Answer, Score, Prompt)
        .join(Prompt, Prompt.id == Answer.prompt_id)
        .outerjoin(Score, Score.answer_id == Answer.id)
        .where(Answer.snapshot_run_id == run.id)
        .order_by(Answer.prompt_id, Answer.model, Answer.run_index)
    ).all()
    answers = [
        AnswerRead(
            id=answer.id,
            prompt_id=answer.prompt_id,
            prompt_text=prompt.text,
            provider=answer.provider,
            model=answer.model,
            run_index=answer.run_index,
            token_count=answer.token_count,
            raw_response=answer.raw_response,
            brand_mentioned=score.brand_mentioned if score else None,
            mention_position=score.mention_position if score else None,
            sentiment=score.sentiment.value if score and score.sentiment else None,
            cited_sources=score.cited_sources if score else [],
        )
        for answer, score, prompt in rows
    ]

    return SnapshotDetail(
        id=run.id,
        project_id=run.project_id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        provider_model=run.provider_model,
        judge_model=run.judge_model,
        judge_prompt_version=run.judge_prompt_version,
        n_runs=run.n_runs,
        error=run.error,
        mention_rate=overall_mention_rate(stats),
        groups=groups,
        providers=_provider_rates(stats),
        answers=answers,
    )
