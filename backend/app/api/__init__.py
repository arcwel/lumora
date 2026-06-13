"""API package — aggregates all route modules under a single router."""

from fastapi import APIRouter

from app.api import dashboard, export, projects, prompts, snapshots

api_router = APIRouter()
api_router.include_router(projects.router)
api_router.include_router(prompts.router)
api_router.include_router(snapshots.router)
api_router.include_router(export.router)
api_router.include_router(dashboard.router)

__all__ = ["api_router"]
