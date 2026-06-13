"""Tests for read-side mention-rate aggregation across N variance runs."""

from __future__ import annotations

from app.aggregate import aggregate_run, latest_run
from app.models.answer import Answer
from app.models.score import Score, Sentiment
from app.models.snapshot import SnapshotRun, SnapshotStatus


def _make_run(session, project, model="gpt-4o-mini", n=3, mentions=2):
    """Create one run with ``n`` answers for the first prompt, ``mentions`` of
    which mention the brand."""

    prompt = project.prompts[0]
    run = SnapshotRun(project_id=project.id, status=SnapshotStatus.COMPLETED, n_runs=n)
    session.add(run)
    session.commit()
    for i in range(1, n + 1):
        ans = Answer(
            snapshot_run_id=run.id,
            prompt_id=prompt.id,
            provider="openai",
            model=model,
            raw_response=f"answer {i}",
            run_index=i,
        )
        session.add(ans)
        session.commit()
        mentioned = i <= mentions
        session.add(
            Score(
                answer_id=ans.id,
                brand_mentioned=mentioned,
                mention_position=2 if mentioned else None,
                sentiment=Sentiment.POSITIVE if mentioned else None,
                cited_sources=[],
                judge_model="judge",
                judge_prompt_hash="abc",
            )
        )
    session.commit()
    return run


def test_mention_rate_is_fraction(db_session, project):
    run = _make_run(db_session, project, n=3, mentions=2)
    stats = aggregate_run(db_session, run.id)
    assert len(stats) == 1
    stat = stats[0]
    assert stat.total_runs == 3
    assert stat.mentions == 2
    assert round(stat.mention_rate, 3) == round(2 / 3, 3)
    assert stat.avg_position == 2.0
    assert stat.sentiments == ["pos", "pos"]


def test_groups_split_by_model(db_session, project):
    run = SnapshotRun(project_id=project.id, status=SnapshotStatus.COMPLETED, n_runs=1)
    db_session.add(run)
    db_session.commit()
    for model in ("gpt-4o-mini", "claude-haiku-4-5-20251001"):
        ans = Answer(
            snapshot_run_id=run.id,
            prompt_id=project.prompts[0].id,
            provider="x",
            model=model,
            raw_response="r",
            run_index=1,
        )
        db_session.add(ans)
        db_session.commit()
        db_session.add(
            Score(
                answer_id=ans.id,
                brand_mentioned=True,
                mention_position=1,
                sentiment=Sentiment.NEUTRAL,
                cited_sources=[],
                judge_model="j",
                judge_prompt_hash="h",
            )
        )
    db_session.commit()

    stats = aggregate_run(db_session, run.id)
    assert {s.model for s in stats} == {"gpt-4o-mini", "claude-haiku-4-5-20251001"}
    assert all(s.mention_rate == 1.0 for s in stats)


def test_latest_run_returns_newest(db_session, project):
    older = _make_run(db_session, project)
    newer = _make_run(db_session, project)
    assert newer.id > older.id
    assert latest_run(db_session, project.id).id == newer.id
