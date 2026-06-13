"""Tests for CSV export (one row per answer)."""

from __future__ import annotations

import csv
import io

from app.exporter import EXPORT_COLUMNS, export_project_csv
from app.models.answer import Answer
from app.models.score import Score, Sentiment
from app.models.snapshot import SnapshotRun, SnapshotStatus


def test_export_has_header_and_one_row_per_answer(db_session, project):
    run = SnapshotRun(project_id=project.id, status=SnapshotStatus.COMPLETED, n_runs=2)
    db_session.add(run)
    db_session.commit()
    for i in (1, 2):
        ans = Answer(
            snapshot_run_id=run.id,
            prompt_id=project.prompts[0].id,
            provider="openai",
            model="gpt-4o-mini",
            raw_response=f"raw {i}",
            run_index=i,
        )
        db_session.add(ans)
        db_session.commit()
        db_session.add(
            Score(
                answer_id=ans.id,
                brand_mentioned=True,
                mention_position=1,
                sentiment=Sentiment.POSITIVE,
                cited_sources=["http://a", "http://b"],
                judge_model="judge",
                judge_prompt_hash="h",
            )
        )
    db_session.commit()

    text = export_project_csv(db_session, project.id)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    assert list(rows[0].keys()) == EXPORT_COLUMNS
    first = rows[0]
    assert first["prompt_text"] == "What is the best widget company?"
    assert first["provider"] == "openai"
    assert first["brand_mentioned"] == "True"
    assert first["cited_sources"] == "http://a; http://b"
    assert first["raw_response"] == "raw 1"
    assert first["run_index"] == "1"


def test_export_includes_unscored_answers(db_session, project):
    run = SnapshotRun(project_id=project.id, status=SnapshotStatus.COMPLETED, n_runs=1)
    db_session.add(run)
    db_session.commit()
    db_session.add(
        Answer(
            snapshot_run_id=run.id,
            prompt_id=project.prompts[0].id,
            provider="gemini",
            model="gemini-2.0-flash",
            raw_response="unscored",
            run_index=1,
        )
    )
    db_session.commit()

    rows = list(csv.DictReader(io.StringIO(export_project_csv(db_session, project.id))))
    assert len(rows) == 1
    assert rows[0]["brand_mentioned"] == ""
    assert rows[0]["sentiment"] == ""
