"""Project CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.project import Project

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    """Payload for creating a project."""

    name: str
    brand_name: str
    aliases: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    monthly_token_budget: int | None = None
    is_active: bool = True


class ProjectRead(BaseModel):
    """Serialized project."""

    id: int
    name: str
    brand_name: str
    aliases: list[str]
    competitors: list[str]
    monthly_token_budget: int | None
    is_active: bool

    model_config = {"from_attributes": True}


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project)).all())


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
