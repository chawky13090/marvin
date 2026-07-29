"""Routes des projets et de leurs instructions persistantes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

import database as db


router = APIRouter(tags=["projects"])


@router.get("/api/projects")
async def list_projects():
    return db.get_projects()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Le nom du projet est requis")
        return normalized


@router.post("/api/projects")
async def create_project(body: ProjectCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom du projet est requis")
    return db.create_project(name, instructions=(body.instructions or None))


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    instructions: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Le nom du projet est requis")
        return normalized


@router.put("/api/projects/{pid}")
async def update_project_route(pid: str, body: ProjectUpdate):
    updated = db.update_project(pid, name=body.name, instructions=body.instructions)
    if not updated:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return updated


@router.delete("/api/projects/{pid}")
async def delete_project(pid: str):
    db.delete_project(pid)
    return {"success": True}
