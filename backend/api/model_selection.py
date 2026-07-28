"""Route HTTP de sélection dynamique d'un modèle Ollama Cloud."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

import cloud_routing


router = APIRouter(prefix="/api/cloud", tags=["models"])
CloudNeed = Literal["general", "code", "vision"]


@router.get("/best-model")
async def get_best_cloud_model(need: CloudNeed = "general") -> dict[str, object]:
    """Résout le meilleur modèle parmi les modèles Cloud réellement disponibles."""
    return {
        "need": need,
        "model": cloud_routing.pick_best_cloud_model(need),
        "installed": cloud_routing.list_installed_cloud_models(),
    }
