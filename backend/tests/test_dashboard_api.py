"""Tests for the read-side dashboard API (``/api/...``).

Uses FastAPI's ``TestClient`` without the lifespan context manager so the
scheduler never starts — the schema and seed data come from the shared
``db_session`` fixture (same temp SQLite engine that ``get_db`` binds to).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models.answer import Answer
from app.models.score import Score, Sentiment
from app.models.snapshot import SnapshotRun, SnapshotStatus

client = TestClient(app)


def _add_run(session, project, *, specs, status=SnapshotStatus.COMPLETED):
    """Create a run. ``specs`` is a list of dicts:
    {prompt_idx, provider, model, n, mentions, position}.
    """

    run = SnapshotRun(project_id=project.id, status=status, n_runs=3)
    session.add(run)
    session.commit()
    for spec in specs:
        prompt = project.prompts[spec.get("prompt_idx", 0)]
        n = spec.get("n", 3)
        mentions = spec.get("mentions", 0)
        position = spec.get("position", 2)
        for i in range(1, n + 1):
            ans = Answer(
                snapshot_run_id=run.id,
                prompt_id=prompt.id,
                provider=spec["provider"],
                model=spec["model"],
                raw_response=f"answer {i}",
                token_count=10,
                run_index=i,
            )
            session.add(ans)
            session.commit()
            mentioned = i <= mentions
            session.add(
                Score(
                    answer_id=ans.id,
                    brand_mentioned=mentioned,
                    mention_position=position if mentioned else None,
                    sentiment=Sentiment.POSITIVE if mentioned else None,
                    cited_sources=["example.com"] if mentioned else [],
                    judge_model="judge",
                    judge_prompt_hash="hash",
                )
            )
    session.commit()
    return run


def _seed_two_providers(session, project):
    """One completed run: openai mentions 2/3, google mentions 1/3 (prompt 0)."""

    return _add_run(
        session,
        project,
        specs=[
            {"prompt_idx": 0, "provider": "openai", "model": "gpt-4o-mini", "n": 3, "mentions": 2},
            {"prompt_idx": 0, "provider": "google", "model": "gemini-2.0-flash", "n": 3, "mentions": 1},
        ],
    )


def test_list_projects_summary(db_session, project):
    _seed_two_providers(db_session, project)

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    summary = data[0]
    assert summary["brand_name"] == "Acme"
    assert summary["n_prompts"] == 2
    # Pooled: 3 mentions of 6 passes = 0.5
    assert round(summary["mention_rate"], 3) == 0.5
    assert summary["latest_status"] == "completed"
    assert summary["sparkline"] == [0.5]


def test_project_detail_with_change(db_session, project):
    # Older run pooled 1/6, newer run pooled 3/6 → +0.333 change.
    _add_run(
        db_session,
        project,
        specs=[
            {"provider": "openai", "model": "gpt-4o-mini", "n": 3, "mentions": 1},
            {"provider": "google", "model": "gemini-2.0-flash", "n": 3, "mentions": 0},
        ],
    )
    _seed_two_providers(db_session, project)

    resp = client.get(f"/api/projects/{project.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["brand_name"] == "Acme"
    assert data["aliases"] == ["AcmeCo"]
    assert data["n_runs"] == 2
    assert round(data["mention_rate"], 3) == 0.5
    assert round(data["mention_rate_change"], 3) == round(0.5 - 1 / 6, 3)
    providers = {p["provider"]: p for p in data["providers"]}
    assert round(providers["openai"]["mention_rate"], 3) == round(2 / 3, 3)
    assert round(providers["google"]["mention_rate"], 3) == round(1 / 3, 3)


def test_project_detail_404(db_session):
    assert client.get("/api/projects/999").status_code == 404


def test_trends_series_per_provider(db_session, project):
    _seed_two_providers(db_session, project)

    resp = client.get(f"/api/projects/{project.id}/trends")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["runs"]) == 1
    providers = {s["provider"]: s["points"] for s in data["series"]}
    assert round(providers["openai"][0], 3) == round(2 / 3, 3)
    assert round(providers["google"][0], 3) == round(1 / 3, 3)


def test_comparison_ranks_providers(db_session, project):
    _seed_two_providers(db_session, project)

    resp = client.get(f"/api/projects/{project.id}/comparison")
    assert resp.status_code == 200
    data = resp.json()
    rates = {p["provider"]: p["mention_rate"] for p in data["providers"]}
    assert rates["openai"] > rates["google"]


def test_comparison_empty_when_no_runs(db_session, project):
    resp = client.get(f"/api/projects/{project.id}/comparison")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] is None
    assert data["providers"] == []


def test_prompt_performance(db_session, project):
    _seed_two_providers(db_session, project)

    resp = client.get(f"/api/projects/{project.id}/prompts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["prompts"]) == 2
    first = data["prompts"][0]
    assert round(first["mention_rate"], 3) == 0.5  # 3/6 on prompt 0
    second = data["prompts"][1]
    assert second["mention_rate"] is None  # no answers for prompt 1


def test_snapshots_pagination(db_session, project):
    for _ in range(3):
        _seed_two_providers(db_session, project)

    resp = client.get(f"/api/projects/{project.id}/snapshots?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["limit"] == 2
    assert len(data["items"]) == 2
    # Newest first.
    assert data["items"][0]["id"] > data["items"][1]["id"]
    assert data["items"][0]["n_answers"] == 6
    assert round(data["items"][0]["mention_rate"], 3) == 0.5


def test_snapshot_detail(db_session, project):
    run = _seed_two_providers(db_session, project)

    resp = client.get(f"/api/projects/{project.id}/snapshots/{run.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run.id
    assert data["status"] == "completed"
    assert len(data["answers"]) == 6
    assert len(data["groups"]) == 2  # two (prompt, model) groups
    assert round(data["mention_rate"], 3) == 0.5
    answer = data["answers"][0]
    assert "raw_response" in answer
    assert answer["brand_mentioned"] in (True, False)


def test_snapshot_detail_wrong_project_404(db_session, project):
    run = _seed_two_providers(db_session, project)
    assert client.get(f"/api/projects/999/snapshots/{run.id}").status_code == 404
