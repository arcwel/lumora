"""Server-rendered dashboard (Task 10).

A thin Jinja2 + HTMX UI layered over the read-side API in
:mod:`app.api.dashboard`. Page routes render full HTML; small HTMX fragment
routes (`*/partial`) return just the piece that changes so interactions stay
snappy without a SPA. Charts are drawn client-side (Chart.js) from the JSON API.

Jinja2 is a declared dependency, but we import it defensively: if it is missing
(e.g. a stripped-down environment), the UI silently disables itself and the JSON
API keeps working. :func:`register_web` wires everything into the app and
reports whether the UI came up.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.api.dashboard import (
    get_project_detail,
    get_prompt_performance,
    list_project_snapshots,
    list_project_summaries,
)
from app.db import get_db
from app.models.project import Project
from app.models.prompt import Prompt
from app.scheduler.runner import run_snapshot_for_project

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent
TEMPLATES_DIR = _BASE / "templates"
STATIC_DIR = _BASE / "static"

def _fmt_pct(value: float | None, digits: int = 0) -> str:
    """Render a 0.0–1.0 rate as a percentage string, or an em dash if missing."""

    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%"


def _fmt_signed_pct(value: float | None, digits: int = 1) -> str:
    """Render a percentage-point delta with an explicit sign (+/−)."""

    if value is None:
        return ""
    pts = value * 100
    sign = "+" if pts >= 0 else "−"
    return f"{sign}{abs(pts):.{digits}f} pts"


def _fmt_dt(value: datetime | None) -> str:
    """Friendly absolute timestamp, e.g. ``Jun 12, 2026 · 14:30``."""

    if value is None:
        return "—"
    return value.strftime("%b %-d, %Y · %H:%M")


def _fmt_ago(value: datetime | None) -> str:
    """Compact relative time, e.g. ``3h ago`` / ``just now`` / ``5d ago``."""

    if value is None:
        return "never"
    now = datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    seconds = (now - value).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


# Defensive import: instantiate Jinja2Templates only if jinja2 is installed.
templates = None
try:  # pragma: no cover - exercised by deployment, not the test sandbox
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["pct"] = _fmt_pct
    templates.env.filters["signed_pct"] = _fmt_signed_pct
    templates.env.filters["dt"] = _fmt_dt
    templates.env.filters["ago"] = _fmt_ago
except Exception as exc:  # noqa: BLE001 - any import/instantiation failure disables the UI
    logger.warning("Dashboard UI disabled (Jinja2 unavailable): %s", exc)

router = APIRouter(include_in_schema=False)


def _require_project(project_id: int, db: Session) -> Project:
    from fastapi import HTTPException

    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    """Dashboard home: a grid of project cards."""

    projects = list_project_summaries(db=db)
    return templates.TemplateResponse(
        request,
        "home.html",
        {"request": request, "projects": projects, "nav": "home"},
    )


@router.get("/projects/new")
def new_project_form(request: Request):
    """Empty form for creating a project."""

    return templates.TemplateResponse(
        request,
        "new_project.html", {"request": request, "nav": "home"}
    )


def _split_csv(raw: str) -> list[str]:
    """Split a comma-separated form field into a clean list of values."""

    return [item.strip() for item in raw.split(",") if item.strip()]


async def _form(request: Request) -> dict[str, str]:
    """Parse a urlencoded form body into a plain dict.

    Deliberately avoids FastAPI's ``Form(...)`` params and Starlette's
    ``request.form()`` — both pull in ``python-multipart``. The dashboard forms
    are simple urlencoded submissions, so ``parse_qsl`` is all we need and keeps
    the dependency surface (and import-time requirements) minimal.
    """

    body = await request.body()
    return dict(parse_qsl(body.decode("utf-8")))


@router.post("/projects/new")
async def create_project_web(request: Request, db: Session = Depends(get_db)):
    """Create a project from the form, then redirect to its settings page."""

    form = await _form(request)
    project = Project(
        name=str(form.get("name", "")).strip(),
        brand_name=str(form.get("brand_name", "")).strip(),
        aliases=_split_csv(str(form.get("aliases", ""))),
        competitors=_split_csv(str(form.get("competitors", ""))),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return RedirectResponse(url=f"/projects/{project.id}/settings", status_code=303)


@router.get("/projects/{project_id}/view")
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    """The main analytics view for a single project."""

    detail = get_project_detail(project_id, db=db)
    prompts = get_prompt_performance(project_id, db=db)
    snapshots = list_project_snapshots(project_id, limit=8, offset=0, db=db)

    # --- Computed fields for the new design ---
    total_mentions = sum(p.mentions for p in detail.providers)

    positions = [p.avg_position for p in detail.providers if p.avg_position is not None]
    avg_position = round(sum(positions) / len(positions), 1) if positions else None

    best_prompt = None
    if prompts.prompts:
        scored = [p for p in prompts.prompts if p.mention_rate is not None and p.mention_rate > 0]
        if scored:
            best_prompt = max(scored, key=lambda p: p.mention_rate)

    sorted_prompts = sorted(
        prompts.prompts,
        key=lambda p: p.mention_rate if p.mention_rate is not None else -1,
        reverse=True,
    )

    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {
            "request": request,
            "nav": "detail",
            "project": detail,
            "prompts": prompts.prompts,
            "sorted_prompts": sorted_prompts,
            "best_prompt": best_prompt,
            "total_mentions": total_mentions,
            "avg_position": avg_position,
            "prompts_json": json.dumps([p.model_dump() for p in prompts.prompts]),
            "prompts_run_at": prompts.run_at,
            "snapshots": snapshots.items,
        },
    )


@router.get("/projects/{project_id}/snapshots/partial")
def snapshots_partial(project_id: int, request: Request, db: Session = Depends(get_db)):
    """HTMX fragment: the recent-snapshots list (used for polling/refresh)."""

    _require_project(project_id, db)
    snapshots = list_project_snapshots(project_id, limit=8, offset=0, db=db)
    return templates.TemplateResponse(
        request,
        "_snapshots.html",
        {"request": request, "snapshots": snapshots.items, "project_id": project_id},
    )


@router.post("/projects/{project_id}/run")
def trigger_run_web(
    project_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Kick off a snapshot run, then return the refreshed snapshots fragment."""

    _require_project(project_id, db)
    background_tasks.add_task(run_snapshot_for_project, project_id)
    snapshots = list_project_snapshots(project_id, limit=8, offset=0, db=db)
    return templates.TemplateResponse(
        request,
        "_snapshots.html",
        {
            "request": request,
            "snapshots": snapshots.items,
            "project_id": project_id,
            "just_triggered": True,
        },
    )


@router.get("/projects/{project_id}/settings")
def project_settings(project_id: int, request: Request, db: Session = Depends(get_db)):
    """Project configuration, prompt management, and schedule."""

    project = _require_project(project_id, db)
    prompts = list(
        db.scalars(
            select_prompts(project_id)
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "nav": "settings",
            "project": project,
            "project_id": project.id,  # used by the _prompts.html include
            "prompts": prompts,
        },
    )


@router.post("/projects/{project_id}/prompts/add")
async def add_prompt_web(
    project_id: int, request: Request, db: Session = Depends(get_db)
):
    """HTMX: add a prompt and return the refreshed prompt list fragment."""

    _require_project(project_id, db)
    form = await _form(request)
    text = str(form.get("text", "")).strip()
    category = str(form.get("category", "")).strip()
    if text:
        db.add(
            Prompt(
                project_id=project_id,
                text=text,
                category=category or None,
            )
        )
        db.commit()
    prompts = list(db.scalars(select_prompts(project_id)).all())
    return templates.TemplateResponse(
        request,
        "_prompts.html",
        {"request": request, "prompts": prompts, "project_id": project_id},
    )


@router.post("/projects/{project_id}/prompts/{prompt_id}/toggle")
def toggle_prompt_web(
    project_id: int, prompt_id: int, request: Request, db: Session = Depends(get_db)
):
    """HTMX: flip a prompt's active flag and return the prompt list fragment."""

    _require_project(project_id, db)
    prompt = db.get(Prompt, prompt_id)
    if prompt is not None and prompt.project_id == project_id:
        prompt.is_active = not prompt.is_active
        db.commit()
    prompts = list(db.scalars(select_prompts(project_id)).all())
    return templates.TemplateResponse(
        request,
        "_prompts.html",
        {"request": request, "prompts": prompts, "project_id": project_id},
    )


def select_prompts(project_id: int):
    """Ordered prompt query for a project (small helper to avoid repetition)."""

    from sqlalchemy import select

    return select(Prompt).where(Prompt.project_id == project_id).order_by(Prompt.id)


def register_web(app: FastAPI) -> bool:
    """Mount static files and (if Jinja2 is available) the page router.

    Returns ``True`` when the HTML UI is enabled. Always mounts ``/static`` —
    it has no Jinja2 dependency and is cheap.
    """

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    if templates is None:
        return False

    app.include_router(router)
    return True
