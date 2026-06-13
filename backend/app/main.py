"""FastAPI application entry point for Lumora."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import api_router
from app.config import settings
from app.db import init_db, is_sqlite
from app.scheduler.runner import shutdown_scheduler, start_scheduler
from app.web import register_web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the database and scheduler on startup; clean up on shutdown."""

    logger.info("Starting %s v%s (%s)", settings.app_name, __version__, settings.environment)
    # SQLite (fallback / local dev) has no migration tooling wired up, so create
    # the schema directly on startup. Postgres deployments own their schema via
    # Alembic — the Docker entrypoint and systemd unit run ``alembic upgrade
    # head`` before the app boots, so we must not race them with create_all.
    if is_sqlite():
        init_db()
        logger.info("SQLite backend detected — ensured schema via create_all")
    else:
        logger.info("Non-SQLite backend — schema managed by Alembic (alembic upgrade head)")
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Self-hosted tracker for how a brand appears in AI assistant answers.",
    lifespan=lifespan,
)

# Mount static assets and (when Jinja2 is installed) the server-rendered
# dashboard. ``ui_enabled`` is False in environments without Jinja2 — the JSON
# API stays fully functional and a friendly root payload is served instead.
#
# The web router is registered BEFORE the JSON API so its literal HTML paths
# (e.g. ``/projects/new``) take precedence over the CRUD integer route
# ``/projects/{project_id}`` — otherwise "new" would be parsed as an id and 422.
ui_enabled = register_web(app)

app.include_router(api_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness/readiness probe."""

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
    }


if not ui_enabled:

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        """Friendly root payload (served when the HTML dashboard is disabled)."""

        return {"name": settings.app_name, "version": __version__, "docs": "/docs"}
