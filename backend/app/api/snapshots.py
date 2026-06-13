"""Snapshot run routes — list runs and trigger a run on demand."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.project import Project
from app.models.snapshot import SnapshotRun, SnapshotStatus
from app.scheduler.runner import run_snapshot_for_project

router = APIRouter(prefix="/projects/{project_id}/snapshots", tags=["snapshots"])


class SnapshotRead(BaseModel):
    """Serialized snapshot run."""

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

    model_config = {"from_attributes": True}


@router.get("", response_model=list[SnapshotRead])
def list_snapshots(project_id: int, db: Session = Depends(get_db)) -> list[SnapshotRun]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    stmt = (
        select(SnapshotRun)
        .where(SnapshotRun.project_id == project_id)
        .order_by(SnapshotRun.id.desc())
    )
    return list(db.scalars(stmt).all())


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def trigger_snapshot(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Kick off a snapshot run in the background for the given project."""

    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    background_tasks.add_task(run_snapshot_for_project, project_id)
    return {"status": "accepted", "project_id": str(project_id)}
