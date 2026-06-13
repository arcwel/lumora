"""Prompt CRUD routes (scoped to a project)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.project import Project
from app.models.prompt import Prompt

router = APIRouter(prefix="/projects/{project_id}/prompts", tags=["prompts"])


class PromptCreate(BaseModel):
    """Payload for creating a prompt."""

    text: str
    category: str | None = None
    is_active: bool = True


class PromptRead(BaseModel):
    """Serialized prompt."""

    id: int
    project_id: int
    text: str
    category: str | None
    is_active: bool

    model_config = {"from_attributes": True}


def _require_project(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", response_model=PromptRead, status_code=status.HTTP_201_CREATED)
def create_prompt(
    project_id: int, payload: PromptCreate, db: Session = Depends(get_db)
) -> Prompt:
    _require_project(project_id, db)
    prompt = Prompt(project_id=project_id, **payload.model_dump())
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.get("", response_model=list[PromptRead])
def list_prompts(project_id: int, db: Session = Depends(get_db)) -> list[Prompt]:
    _require_project(project_id, db)
    stmt = select(Prompt).where(Prompt.project_id == project_id)
    return list(db.scalars(stmt).all())
