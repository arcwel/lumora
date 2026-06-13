"""CSV export of scored answers for a project."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.answer import Answer
from app.models.project import Project
from app.models.score import Score
from app.models.snapshot import SnapshotRun

router = APIRouter(prefix="/projects/{project_id}/export", tags=["export"])

_CSV_COLUMNS = [
    "snapshot_run_id",
    "snapshot_started_at",
    "answer_id",
    "prompt_id",
    "provider",
    "model",
    "token_count",
    "brand_mentioned",
    "mention_position",
    "sentiment",
    "cited_sources",
    "judge_model",
    "judge_prompt_hash",
]


@router.get(".csv")
def export_csv(project_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    """Stream a flat CSV joining snapshot runs, answers, and scores."""

    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    stmt = (
        select(SnapshotRun, Answer, Score)
        .join(Answer, Answer.snapshot_run_id == SnapshotRun.id)
        .outerjoin(Score, Score.answer_id == Answer.id)
        .where(SnapshotRun.project_id == project_id)
        .order_by(SnapshotRun.id, Answer.id)
    )

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for run, answer, score in db.execute(stmt).all():
        writer.writerow(
            {
                "snapshot_run_id": run.id,
                "snapshot_started_at": run.started_at.isoformat() if run.started_at else "",
                "answer_id": answer.id,
                "prompt_id": answer.prompt_id,
                "provider": answer.provider,
                "model": answer.model,
                "token_count": answer.token_count if answer.token_count is not None else "",
                "brand_mentioned": score.brand_mentioned if score else "",
                "mention_position": (
                    score.mention_position if score and score.mention_position is not None else ""
                ),
                "sentiment": score.sentiment.value if score and score.sentiment else "",
                "cited_sources": ";".join(score.cited_sources) if score else "",
                "judge_model": score.judge_model if score else "",
                "judge_prompt_hash": score.judge_prompt_hash if score else "",
            }
        )

    buffer.seek(0)
    filename = f"lumora-project-{project_id}-export.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
