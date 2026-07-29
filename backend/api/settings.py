"""Routes de lecture et d'écriture des paramètres Marvin."""

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, field_validator

import database as db
import cloud_routing
import audit


router = APIRouter(tags=["settings"])


class PrivacyPresetRequest(BaseModel):
    preset: Literal["normal", "hyper", "cloud_max", "ultra"]


class SettingValueRequest(BaseModel):
    value: Any

    @field_validator("value")
    @classmethod
    def validate_size(cls, value: Any) -> Any:
        try:
            serialized = value if isinstance(value, str) else json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Valeur non sérialisable.") from exc
        if len(serialized.encode("utf-8")) > 1_048_576:
            raise ValueError("Valeur de réglage trop volumineuse.")
        return value


SettingKey = Path(
    min_length=1,
    max_length=128,
    pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
)


def _privacy_state() -> dict:
    enabled, overrides = cloud_routing.get_cloud_config()
    return {
        "cloud_enabled": enabled,
        "cloud_overrides": overrides,
        "local_only_lockdown": cloud_routing.is_local_only_lockdown(),
        "ultra_unrestricted": cloud_routing.is_ultra_unrestricted(),
        "cloud_only": cloud_routing.is_cloud_only_mode(),
        "privacy_preset": cloud_routing.get_privacy_preset(),
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

    next_state["privacy_preset"] = payload.preset
    keys = (
        "cloud_overrides",
        "cloud_enabled",
        "ultra_unrestricted",
        "local_only_lockdown",
        "privacy_preset",
    )
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
    current = _privacy_state()
    audit.log_action(
        "privacy_preset_change",
        {
            "previous": previous["privacy_preset"],
            "requested": payload.preset,
        },
        {
            "success": True,
            "effective": current["privacy_preset"],
        },
        source="ui",
    )
    return {"success": True, "preset": payload.preset, **current}


@router.get("/api/settings/{key}")
async def get_setting(key: str = SettingKey):
    return {"key": key, "value": db.get_setting(key)}


@router.put("/api/settings/{key}")
async def set_setting(payload: SettingValueRequest, key: str = SettingKey):
    db.set_setting(key, payload.value)
    return {"success": True}
