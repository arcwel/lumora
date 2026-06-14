"""Tests for the server-rendered dashboard (``app.web``).

Skipped automatically where Jinja2 isn't installed (the UI disables itself in
that case — see ``app.web.register_web``). Where it is present, these drive the
HTML pages, the HTMX fragment routes, and the urlencoded form routes via
``TestClient`` (no lifespan context manager, so the scheduler never starts).
"""

from __future__ import annotations

import pytest

pytest.importorskip("jinja2")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, ui_enabled  # noqa: E402
from app.models.answer import Answer  # noqa: E402
from app.models.score import Score, Sentiment  # noqa: E402
from app.models.snapshot import SnapshotRun, SnapshotStatus  # noqa: E402

pytestmark = pytest.mark.skipif(not ui_enabled, reason="dashboard UI disabled (no Jinja2)")

client = TestClient(app)


def _completed_run(session, project, *, provider="openai", model="gpt-4o-mini", mentions=2):
    run = SnapshotRun(project_id=project.id, status=SnapshotStatus.COMPLETED, n_runs=3)
    session.add(run)
    session.commit()
    for i in range(1, 4):
        ans = Answer(
            snapshot_run_id=run.id,
            prompt_id=project.prompts[0].id,
            provider=provider,
            model=model,
            raw_response=f"answer {i}",
            run_index=i,
        )
        session.add(ans)
        session.commit()
        hit = i <= mentions
        session.add(
            Score(
                answer_id=ans.id,
                brand_mentioned=hit,
                mention_position=1 if hit else None,
                sentiment=Sentiment.POSITIVE if hit else None,
                cited_sources=[],
                judge_model="j",
                judge_prompt_hash="h",
            )
        )
    session.commit()
    return run


def test_home_page_renders(db_session, project):
    _completed_run(db_session, project)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert project.brand_name in resp.text
    assert f"/projects/{project.id}/view" in resp.text
    # Front-end libs wired up (custom Dark Aurora CSS, no Tailwind).
    assert "htmx.org" in resp.text
    assert "chart.js" in resp.text.lower()


def test_home_empty_state(db_session):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No projects yet" in resp.text


def test_project_detail_renders(db_session, project):
    _completed_run(db_session, project)
    resp = client.get(f"/projects/{project.id}/view")
    assert resp.status_code == 200
    assert 'id="trendChart"' in resp.text
    assert 'id="comparisonChart"' in resp.text
    assert "Lumora.initCharts" in resp.text
    assert "Run #" in resp.text  # snapshots list


def test_project_detail_404(db_session):
    assert client.get("/projects/999/view").status_code == 404


def test_settings_renders(db_session, project):
    resp = client.get(f"/projects/{project.id}/settings")
    assert resp.status_code == 200
    assert "Configuration" in resp.text
    assert project.prompts[0].text in resp.text
    assert "/prompts/add" in resp.text


def test_new_project_form_not_shadowed_by_crud_route(db_session):
    # /projects/new must resolve to the HTML form, not the int CRUD route.
    resp = client.get("/projects/new")
    assert resp.status_code == 200
    assert 'name="brand_name"' in resp.text


def test_create_project_via_form(db_session):
    resp = client.post(
        "/projects/new",
        data={"name": "Beta Co", "brand_name": "Beta", "aliases": "B1, B2", "competitors": "Rival"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Beta" in resp.text
    # Aliases were split correctly.
    created = client.get("/api/projects").json()
    beta = next(p for p in created if p["brand_name"] == "Beta")
    assert client.get(f"/api/projects/{beta['id']}").json()["aliases"] == ["B1", "B2"]


def test_add_and_toggle_prompt_fragments(db_session, project):
    # Add a prompt — fragment comes back containing it.
    resp = client.post(
        f"/projects/{project.id}/prompts/add",
        data={"text": "Brand new prompt?", "category": "brand"},
    )
    assert resp.status_code == 200
    assert "Brand new prompt?" in resp.text

    # Toggle the first prompt to inactive.
    resp = client.post(f"/projects/{project.id}/prompts/{project.prompts[0].id}/toggle")
    assert resp.status_code == 200
    assert "Inactive" in resp.text


def test_snapshots_partial(db_session, project):
    _completed_run(db_session, project)
    resp = client.get(f"/projects/{project.id}/snapshots/partial")
    assert resp.status_code == 200
    assert "Run #" in resp.text


def test_trigger_run_returns_fragment(db_session, project):
    resp = client.post(f"/projects/{project.id}/run")
    assert resp.status_code == 200
    assert "Snapshot started" in resp.text


def test_static_assets_served(db_session):
    css = client.get("/static/css/app.css")
    assert css.status_code == 200 and "topbar-nav" in css.text
    js = client.get("/static/js/app.js")
    assert js.status_code == 200 and "initCharts" in js.text
