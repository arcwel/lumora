"""Tests for the multi-provider, N-run snapshot runner.

Provider and judge calls are mocked so the orchestration (fan-out, run_index
tagging, status lifecycle, budget enforcement) is tested without network access.
"""

from __future__ import annotations

import itertools

from app.judge.scorer import ScoreResult
from app.models.answer import Answer
from app.models.score import Sentiment
from app.models.snapshot import SnapshotRun, SnapshotStatus
from app.providers.base import BaseProvider, ProviderError, ProviderResponse


class _FakeProvider(BaseProvider):
    def __init__(self, name, model):
        super().__init__(api_key="fake", model=model)
        self.name = name

    async def query(self, prompt):
        return ProviderResponse(self.name, self.model, "answer", token_count=10)


def _fake_provider_for_model(model, **kwargs):
    name = "openai" if model.startswith("gpt") else "anthropic"
    return _FakeProvider(name, model)


def _install_mocks(monkeypatch, *, mention_pattern=None, query_fails=False):
    from app.scheduler import runner

    monkeypatch.setattr(runner, "provider_for_model", _fake_provider_for_model)

    counter = itertools.count()

    async def fake_score(brand_name, aliases, answer_text, judge_model=None):
        i = next(counter)
        mentioned = mention_pattern(i) if mention_pattern else True
        return ScoreResult(
            brand_mentioned=mentioned,
            mention_position=1 if mentioned else None,
            sentiment=Sentiment.POSITIVE if mentioned else None,
            cited_sources=[],
            judge_model=judge_model or "judge",
            judge_prompt_hash="h",
            judge_token_count=5,
        )

    monkeypatch.setattr(runner, "score_answer", fake_score)

    if query_fails:
        async def boom(self, prompt):
            raise ProviderError("simulated failure")

        monkeypatch.setattr(_FakeProvider, "query", boom)

    return runner


def test_fan_out_across_models_and_runs(monkeypatch, db_session, project):
    runner = _install_mocks(monkeypatch)
    rid = runner.run_snapshot_for_project(
        project.id,
        models=["gpt-4o-mini", "claude-haiku-4-5-20251001"],
        runs_per_prompt=3,
    )
    # 2 prompts × 2 models × 3 passes = 12 answers.
    answers = db_session.query(Answer).filter_by(snapshot_run_id=rid).all()
    assert len(answers) == 12
    assert sorted({a.run_index for a in answers}) == [1, 2, 3]
    assert {a.model for a in answers} == {"gpt-4o-mini", "claude-haiku-4-5-20251001"}

    run = db_session.get(SnapshotRun, rid)
    assert run.status is SnapshotStatus.COMPLETED
    assert run.n_runs == 3
    assert run.started_at is not None and run.completed_at is not None
    assert run.provider_model == "gpt-4o-mini,claude-haiku-4-5-20251001"


def test_provider_failure_skips_answer_without_failing_run(monkeypatch, db_session, project):
    runner = _install_mocks(monkeypatch, query_fails=True)
    rid = runner.run_snapshot_for_project(project.id, models=["gpt-4o-mini"], runs_per_prompt=2)
    run = db_session.get(SnapshotRun, rid)
    assert run.status is SnapshotStatus.COMPLETED
    assert db_session.query(Answer).filter_by(snapshot_run_id=rid).count() == 0


def test_budget_stops_run_early(monkeypatch, db_session, project):
    runner = _install_mocks(monkeypatch)
    # Each answer+judge = 15 tokens; a tiny budget should cut the run short.
    project.monthly_token_budget = 20
    db_session.commit()

    rid = runner.run_snapshot_for_project(project.id, models=["gpt-4o-mini"], runs_per_prompt=3)
    count = db_session.query(Answer).filter_by(snapshot_run_id=rid).count()
    # First answer goes through; budget exhausted before the full 6 (2 prompts × 3).
    assert 0 < count < 6


def test_inactive_project_returns_none(monkeypatch, db_session, project):
    runner = _install_mocks(monkeypatch)
    project.is_active = False
    db_session.commit()
    assert runner.run_snapshot_for_project(project.id) is None
