"""Routes CRUD des notes Marvin."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import database as db
import note_lifecycle


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
    result = await note_lifecycle.create(body.title, body.content, body.tags, body.pinned)
    return {**result["note"], "consistency": result["consistency"], "warnings": result["warnings"]}


class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None


@router.put("/api/notes/{nid}")
async def update_note(nid: str, body: NoteUpdate):
    result = await note_lifecycle.update(nid, body.model_dump(exclude_none=True))
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Note introuvable")
    return {**result["note"], "consistency": result["consistency"], "warnings": result["warnings"]}


@router.delete("/api/notes/{nid}")
async def delete_note(nid: str, confirmed: bool = False):
    if not confirmed:
        raise HTTPException(status_code=409, detail="Confirmation explicite requise")
    result = await note_lifecycle.delete(nid)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Note introuvable")
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result)
    return result
