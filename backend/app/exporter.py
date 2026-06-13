"""CSV export of a project's scored answers — one row per captured answer.

Shared by the CLI ``export`` command. Joins each ``Answer`` to its originating
``Prompt`` and (outer) its ``Score`` so unscored answers still export, with the
score columns left blank.
"""

from __future__ import annotations

import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.prompt import Prompt
from app.models.score import Score
from app.models.snapshot import SnapshotRun

#: Column order for the export. Leading columns match the documented schema;
#: ``run_index`` / ``snapshot_run_id`` trail as provenance for the N-run model.
EXPORT_COLUMNS = [
    "prompt_text",
    "provider",
    "model",
    "brand_mentioned",
    "mention_position",
    "sentiment",
    "cited_sources",
    "raw_response",
    "timestamp",
    "run_index",
    "snapshot_run_id",
]


def _row(answer: Answer, score: Score | None, prompt: Prompt) -> dict[str, object]:
    return {
        "prompt_text": prompt.text,
        "provider": answer.provider,
        "model": answer.model,
        "brand_mentioned": score.brand_mentioned if score else "",
        "mention_position": (
            score.mention_position if score and score.mention_position is not None else ""
        ),
        "sentiment": score.sentiment.value if score and score.sentiment else "",
        "cited_sources": "; ".join(score.cited_sources) if score else "",
        "raw_response": answer.raw_response,
        "timestamp": answer.created_at.isoformat() if answer.created_at else "",
        "run_index": answer.run_index,
        "snapshot_run_id": answer.snapshot_run_id,
    }


def export_project_csv(session: Session, project_id: int) -> str:
    """Return CSV text (with header) of every answer captured for a project."""

    rows = session.execute(
        select(Answer, Score, Prompt)
        .join(Prompt, Prompt.id == Answer.prompt_id)
        .join(SnapshotRun, SnapshotRun.id == Answer.snapshot_run_id)
        .outerjoin(Score, Score.answer_id == Answer.id)
        .where(SnapshotRun.project_id == project_id)
        .order_by(Answer.snapshot_run_id, Answer.prompt_id, Answer.model, Answer.run_index)
    ).all()

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for answer, score, prompt in rows:
        writer.writerow(_row(answer, score, prompt))
    return buffer.getvalue()
