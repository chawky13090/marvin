"""Routes CRUD des tâches Marvin."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import database as db


router = APIRouter(tags=["tasks"])


@router.get("/api/tasks")
async def list_tasks(status: str | None = None, priority: str | None = None):
    return db.list_tasks(status=status, priority=priority)


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    due_date: str | None = None
    tags: list[str] = Field(default_factory=list)


@router.post("/api/tasks")
async def create_task(body: TaskCreate):
    return db.create_task(
        title=body.title,
        description=body.description,
        priority=body.priority,
        due_date=body.due_date,
        tags=body.tags,
    )


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: str | None = None
    tags: list[str] | None = None


@router.put("/api/tasks/{tid}")
async def update_task(tid: str, body: TaskUpdate):
    task = db.update_task(tid, body.model_dump(exclude_none=True))
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return task


@router.delete("/api/tasks/{tid}")
async def delete_task(tid: str):
    # L'accès SQLite peut attendre un worker de fond : ne jamais bloquer l'event loop.
    await asyncio.to_thread(db.delete_task, tid)
    return {"success": True}
