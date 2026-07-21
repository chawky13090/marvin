"""Routes CRUD des notes Marvin."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import database as db


router = APIRouter(tags=["notes"])


@router.get("/api/notes")
async def list_notes(search: str | None = None, pinned: bool | None = None):
    return db.list_notes(search=search, pinned=pinned)


class NoteCreate(BaseModel):
    title: str
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False


@router.post("/api/notes")
async def create_note(body: NoteCreate):
    return db.create_note(body.title, body.content, body.tags, body.pinned)


class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None


@router.put("/api/notes/{nid}")
async def update_note(nid: str, body: NoteUpdate):
    note = db.update_note(nid, body.model_dump(exclude_none=True))
    if not note:
        raise HTTPException(status_code=404, detail="Note introuvable")
    return note


@router.delete("/api/notes/{nid}")
async def delete_note(nid: str):
    db.delete_note(nid)
    return {"success": True}
