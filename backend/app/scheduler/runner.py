"""APScheduler configuration and the snapshot-run job.

The scheduler runs in-process (background thread) for the MVP. A snapshot run
fans out across every configured provider and repeats each prompt ``N`` times
(default 3) to account for AI answer non-determinism: for each prompt × provider
× pass it queries the provider, persists an ``Answer`` (tagged with its
``run_index``), judges it, and persists a ``Score``. Mention rate is then a
fraction (e.g. "mentioned in 2/3 runs") rather than a binary flag.

Projects carry an optional ``cron_schedule``; ``start_scheduler`` registers a
recurring job for each active, scheduled project so snapshots run on a cadence
(e.g. weekly on Mondays).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.budget import is_budget_exhausted
from app.config import settings
from app.db import SessionLocal
from app.judge.rubric import CURRENT_JUDGE_PROMPT_VERSION
from app.judge.scorer import score_answer
from app.models.answer import Answer
from app.models.project import Project
from app.models.prompt import Prompt
from app.models.score import Score
from app.models.snapshot import SnapshotRun, SnapshotStatus
from app.providers import BaseProvider, ProviderError, provider_for_model

logger = logging.getLogger(__name__)

#: A progress sink: receives a human-readable status line during a run. Used by
#: the CLI to stream real-time progress; defaults to a no-op for scheduled jobs.
ProgressCallback = Callable[[str], None]


def _noop(_message: str) -> None:  # pragma: no cover - trivial default
    pass


_scheduler: BackgroundScheduler | None = None


def run_snapshot_for_project(
    project_id: int,
    *,
    models: Sequence[str] | None = None,
    runs_per_prompt: int | None = None,
    progress: ProgressCallback | None = None,
) -> int | None:
    """Execute a snapshot run for a single project.

    Creates a ``SnapshotRun`` (PENDING → RUNNING → COMPLETED/FAILED), then for
    each active prompt queries every configured provider ``runs_per_prompt``
    times, judging each answer. Returns the run id, or ``None`` if the project
    was missing/inactive.
    """

    emit = progress or _noop
    models = list(models) if models is not None else settings.snapshot_model_list
    runs_per_prompt = runs_per_prompt or settings.runs_per_prompt

    session = SessionLocal()
    run: SnapshotRun | None = None
    try:
        project = session.get(Project, project_id)
        if project is None or not project.is_active:
            logger.warning("Skipping snapshot: project %s missing/inactive", project_id)
            emit(f"Project {project_id} is missing or inactive; nothing to do.")
            return None

        # Lifecycle: record the run as PENDING first so it exists even if setup
        # fails, then flip to RUNNING with a start timestamp.
        run = SnapshotRun(
            project_id=project.id,
            status=SnapshotStatus.PENDING,
            provider_model=",".join(models),
            judge_model=settings.default_judge_model,
            judge_prompt_version=CURRENT_JUDGE_PROMPT_VERSION,
            n_runs=runs_per_prompt,
        )
        session.add(run)
        session.commit()

        run.status = SnapshotStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        session.commit()
        emit(
            f"Snapshot run #{run.id} started for {project.brand_name!r} "
            f"({len(models)} model(s) × {runs_per_prompt} pass(es))."
        )

        answered, scored = asyncio.run(
            _execute_snapshot(session, project, run, models, runs_per_prompt, emit)
        )
        logger.info(
            "Snapshot run %s for project %s: %d answers, %d scored",
            run.id,
            project.id,
            answered,
            scored,
        )

        run.status = SnapshotStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        session.commit()
        emit(f"Snapshot run #{run.id} completed: {answered} answers, {scored} scored.")
        return run.id
    except Exception as exc:
        session.rollback()
        logger.exception("Snapshot run failed for project %s", project_id)
        emit(f"Snapshot run failed: {exc}")
        # Best-effort: mark the run failed so it isn't left dangling in RUNNING.
        try:
            if run is not None and run.id is not None:
                run.status = SnapshotStatus.FAILED
                run.completed_at = datetime.now(timezone.utc)
                run.error = str(exc)[:2000]
                session.commit()
        except Exception:  # pragma: no cover - defensive bookkeeping
            session.rollback()
        raise
    finally:
        session.close()


def _resolve_providers(
    models: Sequence[str], emit: ProgressCallback
) -> list[tuple[str, BaseProvider]]:
    """Instantiate each model's provider, dropping any without a configured key."""

    resolved: list[tuple[str, BaseProvider]] = []
    for model in models:
        provider = provider_for_model(model)
        if not provider.is_configured():
            logger.warning("Skipping model %s: provider %s not configured", model, provider.name)
            emit(f"  skipping {model}: {provider.name} API key not configured")
            continue
        resolved.append((model, provider))
    return resolved


async def _execute_snapshot(
    session: Session,
    project: Project,
    run: SnapshotRun,
    models: Sequence[str],
    runs_per_prompt: int,
    emit: ProgressCallback,
) -> tuple[int, int]:
    """Fan out across providers and variance passes; persist answers and scores.

    Returns ``(answers_persisted, scores_persisted)``. Per-call provider/judge
    failures are logged and skipped so one bad call can't fail the whole run.
    Honors the project's monthly token budget, stopping early once exhausted.
    """

    judge_model = run.judge_model or settings.default_judge_model
    providers = _resolve_providers(models, emit)
    if not providers:
        emit("  no providers configured; skipping all prompts")
        return 0, 0

    prompts = session.scalars(
        select(Prompt).where(
            Prompt.project_id == project.id, Prompt.is_active.is_(True)
        )
    ).all()

    answered = 0
    scored = 0
    for prompt in prompts:
        preview = prompt.text if len(prompt.text) <= 60 else prompt.text[:57] + "..."
        emit(f'Prompt #{prompt.id}: "{preview}"')
        for model, provider in providers:
            for run_index in range(1, runs_per_prompt + 1):
                if is_budget_exhausted(session, project):
                    logger.warning(
                        "Monthly token budget exhausted for project %s; "
                        "stopping run %s early",
                        project.id,
                        run.id,
                    )
                    emit("  monthly token budget exhausted; stopping run early")
                    return answered, scored

                emit(f"  {model} · pass {run_index}/{runs_per_prompt} · querying...")
                try:
                    result = await provider.query(prompt.text)
                except ProviderError:
                    logger.exception(
                        "Provider %s failed on prompt %s pass %s (run %s)",
                        model,
                        prompt.id,
                        run_index,
                        run.id,
                    )
                    emit(f"  {model} · pass {run_index} · provider error (skipped)")
                    continue

                answer = Answer(
                    snapshot_run_id=run.id,
                    prompt_id=prompt.id,
                    provider=result.provider,
                    model=result.model,
                    raw_response=result.text,
                    token_count=result.token_count,
                    run_index=run_index,
                )
                session.add(answer)
                session.commit()
                answered += 1

                emit(f"  {model} · pass {run_index} · scoring...")
                try:
                    score_result = await score_answer(
                        brand_name=project.brand_name,
                        aliases=project.aliases,
                        answer_text=result.text,
                        judge_model=judge_model,
                    )
                except ProviderError:
                    logger.exception(
                        "Judge %s failed on answer %s (run %s)",
                        judge_model,
                        answer.id,
                        run.id,
                    )
                    emit(f"  {model} · pass {run_index} · judge error (skipped)")
                    continue

                session.add(
                    Score(
                        answer_id=answer.id,
                        brand_mentioned=score_result.brand_mentioned,
                        mention_position=score_result.mention_position,
                        sentiment=score_result.sentiment,
                        cited_sources=score_result.cited_sources,
                        judge_model=score_result.judge_model,
                        judge_prompt_hash=score_result.judge_prompt_hash,
                    )
                )
                # Fold judge token spend into the answer's tally so the monthly
                # budget reflects total provider + judge usage.
                if score_result.judge_token_count:
                    answer.token_count = (answer.token_count or 0) + score_result.judge_token_count
                session.commit()
                scored += 1
                mention = "mentioned" if score_result.brand_mentioned else "not mentioned"
                emit(f"  {model} · pass {run_index} · scored ({mention})")

    return answered, scored


def get_scheduler() -> BackgroundScheduler:
    """Return the process-wide scheduler, creating it on first use."""

    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)
    return _scheduler


def load_scheduled_jobs(scheduler: BackgroundScheduler | None = None) -> int:
    """Register a recurring job for every active project with a cron schedule.

    Returns the number of jobs registered. Safe to call repeatedly — each job
    id is project-scoped and replaces any existing one.
    """

    scheduler = scheduler or get_scheduler()
    session = SessionLocal()
    try:
        projects = session.scalars(
            select(Project).where(
                Project.is_active.is_(True), Project.cron_schedule.is_not(None)
            )
        ).all()
        for project in projects:
            _register_job(scheduler, project.id, project.cron_schedule)  # type: ignore[arg-type]
        if projects:
            logger.info("Loaded %d scheduled project job(s)", len(projects))
        return len(projects)
    finally:
        session.close()


def start_scheduler() -> BackgroundScheduler | None:
    """Start the scheduler if enabled, loading all scheduled project jobs."""

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled via settings")
        return None

    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started (tz=%s)", settings.scheduler_timezone)
    load_scheduled_jobs(scheduler)
    return scheduler


def shutdown_scheduler() -> None:
    """Stop the scheduler if it is running."""

    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
    _scheduler = None


def _register_job(
    scheduler: BackgroundScheduler, project_id: int, cron_expression: str
) -> None:
    """Add (or replace) a project's recurring snapshot job on the scheduler."""

    scheduler.add_job(
        run_snapshot_for_project,
        trigger=CronTrigger.from_crontab(cron_expression, timezone=settings.scheduler_timezone),
        args=[project_id],
        id=f"snapshot-project-{project_id}",
        replace_existing=True,
    )


def schedule_project(project_id: int, cron_expression: str) -> None:
    """Persist a project's cron schedule and register the recurring job.

    The cron expression is validated and stored on the ``Project`` row so it
    survives restarts (``start_scheduler`` reloads it). If the scheduler is
    already running, the job is registered immediately.
    """

    # Validate the expression up front so a bad cron fails loudly here.
    CronTrigger.from_crontab(cron_expression, timezone=settings.scheduler_timezone)

    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        project.cron_schedule = cron_expression
        session.commit()
    finally:
        session.close()

    scheduler = get_scheduler()
    if scheduler.running:
        _register_job(scheduler, project_id, cron_expression)
    logger.info("Scheduled project %s with cron %r", project_id, cron_expression)
