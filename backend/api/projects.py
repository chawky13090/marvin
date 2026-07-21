"""Routes des projets et de leurs instructions persistantes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database as db


router = APIRouter(tags=["projects"])


@router.get("/api/projects")
async def list_projects():
    return db.get_projects()


class ProjectCreate(BaseModel):
    name: str
    instructions: str | None = None


@router.post("/api/projects")
async def create_project(body: ProjectCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom du projet est requis")
    return db.create_project(name, instructions=(body.instructions or None))


class ProjectUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None


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
