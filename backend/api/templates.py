"""Routes CRUD des modèles d'appels d'outils Marvin."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

import database as db


router = APIRouter(tags=["templates"])


class TemplateCreate(BaseModel):
    name: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    description: str = ""
    category: str = "general"


@router.get("/api/templates")
async def list_templates(tool_name: str | None = None, category: str | None = None):
    return db.list_templates(tool_name=tool_name, category=category)


@router.post("/api/templates")
async def create_template(body: TemplateCreate):
    return db.save_template(
        body.name,
        body.tool_name,
        body.args,
        body.description,
        body.category,
    )


@router.delete("/api/templates/{tid}")
async def delete_template(tid: str):
    db.delete_template(tid)
    return {"success": True}
