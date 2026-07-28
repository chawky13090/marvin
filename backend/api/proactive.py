"""Routes HTTP du briefing et de la configuration proactive de Marvin."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import audit
import bug_log
import database as db
import proactive_service
import tools as tool_module


router = APIRouter(prefix="/api", tags=["proactive"])
_TIME_PATTERN = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
_VOICE_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class _ClosedPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BriefingPatch(_ClosedPatch):
    enabled: bool | None = None
    time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    voice: bool | None = None
    voice_name: str | None = Field(default=None, pattern=_VOICE_PATTERN)


class AnticipationPatch(_ClosedPatch):
    enabled: bool | None = None
    interval_min: int | None = Field(default=None, ge=5, le=1440)
    overdue_tasks: bool | None = None
    upcoming_events: bool | None = None
    upcoming_events_min: int | None = Field(default=None, ge=1, le=1440)
    max_notify: int | None = Field(default=None, ge=1, le=50)


class QuietHoursPatch(_ClosedPatch):
    enabled: bool | None = None
    start: str | None = Field(default=None, pattern=_TIME_PATTERN)
    end: str | None = Field(default=None, pattern=_TIME_PATTERN)


class ProactiveConfigPatch(BriefingPatch):
    """Patch partiel; les champs racine gardent l'ancien contrat du briefing matinal."""

    morning_briefing: BriefingPatch | None = None
    evening_recap: BriefingPatch | None = None
    anticipation: AnticipationPatch | None = None
    quiet_hours: QuietHoursPatch | None = None


def _patch_values(value: BaseModel) -> dict[str, object]:
    return value.model_dump(exclude_none=True, exclude_unset=True)


@router.get("/briefing")
async def daily_briefing() -> dict:
    """Produit le briefing du jour depuis l'outil public partagé."""
    try:
        result = await tool_module.TOOLS_REGISTRY["daily_briefing"]({})
    except Exception as exc:
        incident_id = uuid.uuid4().hex
        bug_log.log_bug(
            "daily_briefing_route",
            type(exc).__name__,
            context={"incident_id": incident_id, "exception_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Le briefing est temporairement indisponible.",
                "incident_id": incident_id,
            },
        ) from None
    if not isinstance(result, dict) or result.get("error") or result.get("success") is False:
        incident_id = uuid.uuid4().hex
        bug_log.log_bug(
            "daily_briefing_result",
            "BriefingResultFailure",
            context={
                "incident_id": incident_id,
                "result_type": type(result).__name__,
                "reported_error": bool(isinstance(result, dict) and result.get("error")),
            },
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Le briefing est temporairement indisponible.",
                "incident_id": incident_id,
            },
        )
    return result


@router.get("/proactive")
async def get_proactive() -> dict[str, object]:
    return proactive_service.get_config()


@router.post("/proactive")
async def set_proactive(body: ProactiveConfigPatch) -> dict[str, object]:
    config = proactive_service.get_config()
    supplied = body.model_fields_set

    if body.morning_briefing is not None:
        morning_patch = _patch_values(body.morning_briefing)
    elif not supplied.intersection({"evening_recap", "anticipation"}):
        morning_patch = {
            key: value
            for key, value in _patch_values(body).items()
            if key in {"enabled", "time", "voice", "voice_name"}
        }
    else:
        morning_patch = {}
    config["morning_briefing"].update(morning_patch)

    if body.evening_recap is not None:
        config["evening_recap"].update(_patch_values(body.evening_recap))
    if body.anticipation is not None:
        config["anticipation"].update(_patch_values(body.anticipation))
    if body.quiet_hours is not None:
        config["quiet_hours"].update(_patch_values(body.quiet_hours))

    normalized = proactive_service.with_defaults(config)
    db.set_setting("proactive_config", normalized)
    audit.log_action(
        "proactive_config_update",
        {
            "sections": sorted(
                supplied.intersection(
                    {"morning_briefing", "evening_recap", "anticipation", "quiet_hours"}
                )
            ),
            "legacy_morning_fields": sorted(
                supplied.intersection({"enabled", "time", "voice", "voice_name"})
            ),
        },
        {"success": True},
        source="ui",
    )
    return {"success": True, "config": normalized}


@router.post("/proactive/run")
async def run_proactive_now(
    kind: Literal["morning", "evening", "anticipation"] = "morning",
) -> dict:
    """Déclenche explicitement une seule branche proactive."""
    config = proactive_service.get_config()
    if kind == "evening":
        return await proactive_service.run_evening_recap(config["evening_recap"])
    if kind == "anticipation":
        return await proactive_service.run_anticipation(config["anticipation"], force=True)
    return await proactive_service.run_morning_briefing(config["morning_briefing"])
