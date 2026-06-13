"""FastAPI application entry point for Lumora."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app import __version__
from app.api import api_router
from app.config import settings
from app.db import init_db
from app.scheduler.runner import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the database and scheduler on startup; clean up on shutdown."""

    logger.info("Starting %s v%s (%s)", settings.app_name, __version__, settings.environment)
    init_db()
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


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    """Friendly root payload."""

    return {"name": settings.app_name, "version": __version__, "docs": "/docs"}
