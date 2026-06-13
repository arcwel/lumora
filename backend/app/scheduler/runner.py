"""APScheduler configuration and the snapshot-run job.

The scheduler runs in-process (background thread) for the MVP. The job body
orchestrates: for each active prompt, query each configured provider, persist
``Answer`` rows, judge them, and persist ``Score`` rows. Provider/judge calls
are scaffold stubs, so the orchestration is wired but not yet live.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import SessionLocal
from app.models.project import Project
from app.models.snapshot import SnapshotRun, SnapshotStatus

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def run_snapshot_for_project(project_id: int) -> None:
    """Execute a snapshot run for a single project.

    Creates a ``SnapshotRun`` and walks it through its lifecycle. Provider and
    judge integration is stubbed; the surrounding bookkeeping is real.
    """

    session = SessionLocal()
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
        )
        session.add(run)
        session.commit()

        # TODO: for each active prompt -> query providers -> persist Answer
        #       -> judge.score_answer -> persist Score. Stubbed for scaffold.
        logger.info("Snapshot run %s created for project %s (stubbed)", run.id, project.id)

        run.status = SnapshotStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        session.commit()
    except Exception:  # pragma: no cover - defensive bookkeeping
        session.rollback()
        logger.exception("Snapshot run failed for project %s", project_id)
        raise
    finally:
        session.close()


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
