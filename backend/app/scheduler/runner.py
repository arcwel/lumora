"""APScheduler configuration and the snapshot-run job.

The scheduler runs in-process (background thread) for the MVP. The job body
orchestrates: for each active prompt, query each configured provider, persist
``Answer`` rows, judge them, and persist ``Score`` rows. Provider/judge calls
are scaffold stubs, so the orchestration is wired but not yet live.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.budget import is_budget_exhausted
from app.config import settings
from app.judge.rubric import CURRENT_JUDGE_PROMPT_VERSION
from app.judge.scorer import score_answer
from app.models.answer import Answer
from app.models.project import Project
from app.models.prompt import Prompt
from app.models.score import Score
from app.models.snapshot import SnapshotRun, SnapshotStatus
from app.providers import ProviderError, provider_for_model

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def run_snapshot_for_project(project_id: int) -> None:
    """Execute a snapshot run for a single project.

    Creates a ``SnapshotRun``, queries the provider for each active prompt,
    judges the answers, and walks the run through its lifecycle.
    """

    session = SessionLocal()
    run: SnapshotRun | None = None
    try:
        project = session.get(Project, project_id)
        if project is None or not project.is_active:
            logger.warning("Skipping snapshot: project %s missing/inactive", project_id)
            return

        run = SnapshotRun(
            project_id=project.id,
            status=SnapshotStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            provider_model=settings.default_provider_model,
            judge_model=settings.default_judge_model,
            judge_prompt_version=CURRENT_JUDGE_PROMPT_VERSION,
        )
        session.add(run)
        session.commit()

        # Provider/judge calls are async; drive them from this sync job.
        answered, scored = asyncio.run(_execute_snapshot(session, project, run))
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
    except Exception:
        session.rollback()
        logger.exception("Snapshot run failed for project %s", project_id)
        # Best-effort: mark the run failed so it isn't left dangling in RUNNING.
        try:
            if run is not None and run.id is not None:
                run.status = SnapshotStatus.FAILED
                run.completed_at = datetime.now(timezone.utc)
                session.commit()
        except Exception:  # pragma: no cover - defensive bookkeeping
            session.rollback()
        raise
    finally:
        session.close()


async def _execute_snapshot(
    session: Session, project: Project, run: SnapshotRun
) -> tuple[int, int]:
    """Query the provider for each active prompt, persist answers, and judge them.

    Returns ``(answers_persisted, scores_persisted)``. Per-prompt provider/judge
    failures are logged and skipped so one bad call can't fail the whole run.
    Honors the project's monthly token budget, stopping early once exhausted.
    """

    provider_model = run.provider_model or settings.default_provider_model
    judge_model = run.judge_model or settings.default_judge_model
    provider = provider_for_model(provider_model)

    prompts = session.scalars(
        select(Prompt).where(
            Prompt.project_id == project.id, Prompt.is_active.is_(True)
        )
    ).all()

    answered = 0
    scored = 0
    for prompt in prompts:
        if is_budget_exhausted(session, project):
            logger.warning(
                "Monthly token budget exhausted for project %s; stopping run %s early",
                project.id,
                run.id,
            )
            break

        try:
            result = await provider.query(prompt.text)
        except ProviderError:
            logger.exception(
                "Provider %s failed on prompt %s (run %s)",
                provider_model,
                prompt.id,
                run.id,
            )
            continue

        answer = Answer(
            snapshot_run_id=run.id,
            prompt_id=prompt.id,
            provider=result.provider,
            model=result.model,
            raw_response=result.text,
            token_count=result.token_count,
        )
        session.add(answer)
        session.commit()
        answered += 1

        try:
            score_result = await score_answer(
                brand_name=project.brand_name,
                aliases=project.aliases,
                answer_text=result.text,
                judge_model=judge_model,
            )
        except ProviderError:
            logger.exception(
                "Judge %s failed on answer %s (run %s)", judge_model, answer.id, run.id
            )
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
        # Fold judge token spend into the answer's tally so the monthly budget
        # reflects total provider + judge usage.
        if score_result.judge_token_count:
            answer.token_count = (answer.token_count or 0) + score_result.judge_token_count
        session.commit()
        scored += 1

    return answered, scored


def get_scheduler() -> BackgroundScheduler:
    """Return the process-wide scheduler, creating it on first use."""

    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)
    return _scheduler


def start_scheduler() -> BackgroundScheduler | None:
    """Start the scheduler if enabled. Returns the scheduler or ``None``."""

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled via settings")
        return None

    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started (tz=%s)", settings.scheduler_timezone)
    return scheduler


def shutdown_scheduler() -> None:
    """Stop the scheduler if it is running."""

    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
    _scheduler = None


def schedule_project(project_id: int, cron_expression: str) -> None:
    """Register a recurring snapshot job for a project using a cron expression."""

    scheduler = get_scheduler()
    scheduler.add_job(
        run_snapshot_for_project,
        trigger=CronTrigger.from_crontab(cron_expression, timezone=settings.scheduler_timezone),
        args=[project_id],
        id=f"snapshot-project-{project_id}",
        replace_existing=True,
    )
    logger.info("Scheduled project %s with cron %r", project_id, cron_expression)
