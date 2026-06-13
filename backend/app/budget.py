"""Per-project monthly token-budget accounting.

Tokens are tallied from persisted ``Answer`` rows (provider + judge usage is
recorded there) for the current calendar month, and compared against the
project's ``monthly_token_budget``. A ``None`` budget means unlimited.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.project import Project
from app.models.snapshot import SnapshotRun


def _month_start(now: datetime | None = None) -> datetime:
    """Return midnight UTC on the first day of the current month."""

    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def tokens_used_this_month(session: Session, project_id: int) -> int:
    """Sum ``token_count`` across all answers for ``project_id`` this month."""

    stmt = (
        select(func.coalesce(func.sum(Answer.token_count), 0))
        .join(SnapshotRun, Answer.snapshot_run_id == SnapshotRun.id)
        .where(SnapshotRun.project_id == project_id)
        .where(Answer.created_at >= _month_start())
    )
    return int(session.execute(stmt).scalar_one() or 0)


def remaining_budget(session: Session, project: Project) -> int | None:
    """Tokens remaining this month, or ``None`` when the budget is unlimited."""

    if project.monthly_token_budget is None:
        return None
    used = tokens_used_this_month(session, project.id)
    return max(project.monthly_token_budget - used, 0)


def is_budget_exhausted(session: Session, project: Project) -> bool:
    """``True`` when a budget is set and this month's usage meets/exceeds it."""

    remaining = remaining_budget(session, project)
    return remaining is not None and remaining <= 0
