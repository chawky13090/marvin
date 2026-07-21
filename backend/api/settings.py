"""Routes de lecture et d'écriture des paramètres Marvin."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import database as db
import cloud_routing


router = APIRouter(tags=["settings"])


class PrivacyPresetRequest(BaseModel):
    preset: Literal["normal", "hyper", "cloud_max", "ultra"]


def _privacy_state() -> dict:
    enabled, overrides = cloud_routing.get_cloud_config()
    return {
        "cloud_enabled": enabled,
        "cloud_overrides": overrides,
        "local_only_lockdown": cloud_routing.is_local_only_lockdown(),
        "ultra_unrestricted": cloud_routing.is_ultra_unrestricted(),
        "cloud_only": cloud_routing.is_cloud_only_mode(),
    }


@router.put("/api/settings/privacy-preset")
async def set_privacy_preset(payload: PrivacyPresetRequest):
    """Applique un preset comme une seule opération logique avec rollback best-effort."""
    previous = _privacy_state()
    next_state = dict(previous)
    if payload.preset == "normal":
        next_state.update(local_only_lockdown=False, ultra_unrestricted=False)
    elif payload.preset == "hyper":
        next_state.update(
            local_only_lockdown=True,
            cloud_enabled=False,
            ultra_unrestricted=False,
        )
    else:
        best = cloud_routing.pick_best_cloud_model("general")
        if not best:
            raise HTTPException(
                status_code=409,
                detail="Aucun modèle Ollama Cloud installé; preset cloud refusé sans repli local.",
            )
        next_state.update(
            local_only_lockdown=False,
            cloud_enabled=True,
            cloud_overrides={"agent": best, "chat": best, "analysis": best},
            ultra_unrestricted=payload.preset == "ultra",
        )

    keys = ("cloud_overrides", "cloud_enabled", "ultra_unrestricted", "local_only_lockdown")
    try:
        # Ultra est écrit après la configuration cloud. Hyper est écrit en dernier afin
        # que le coupe-circuit gagne même si un ancien état était incohérent.
        for key in keys:
            db.set_setting(key, next_state[key])
    except Exception as exc:
        for key in keys:
            try:
                db.set_setting(key, previous[key])
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="Application du preset annulée et restaurée.") from exc
    return {"success": True, "preset": payload.preset, **_privacy_state()}


@router.get("/api/settings/{key}")
async def get_setting(key: str):
    return {"key": key, "value": db.get_setting(key)}


@router.put("/api/settings/{key}")
async def set_setting(key: str, request: Request):
    body = await request.json()
    db.set_setting(key, body.get("value"))
    return {"success": True}
