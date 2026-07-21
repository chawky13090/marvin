"""API des recettes déclaratives Marvin Cortex."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import cortex


router = APIRouter(prefix="/api/cortex", tags=["cortex"])


class RecipeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    contract: dict = Field(default_factory=dict)


@router.get("/recipes")
async def recipes_list():
    return {"recipes": cortex.list_recipes()}


@router.post("/recipes")
async def recipes_create(payload: RecipeCreate):
    try:
        return {"success": True, "recipe": cortex.save_recipe(payload.name, payload.contract, payload.description)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/recipes/{recipe_id}")
async def recipes_delete(recipe_id: str):
    if not cortex.delete_recipe(recipe_id):
        raise HTTPException(status_code=404, detail="Recette Cortex introuvable.")
    return {"success": True}
