"""Routes d'apprentissage, configuration matérielle, Telegram et audit."""

import asyncio

from typing import Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

import database as db
import tools as tool_module
import audit


router = APIRouter(tags=["runtime-config"])


def _learning_snapshot(learning_module) -> dict:
    """Read the local learning stores away from the asynchronous event loop."""
    return {
        "counts": learning_module.count_learned(),
        "facts": learning_module.list_learned("facts", 200),
        "qa": learning_module.list_learned("qa", 100),
    }


@router.get("/api/telegram")
async def get_telegram():
    config = tool_module._telegram_cfg()
    return {
        "enabled": bool(config.get("enabled")),
        "chat_id": config.get("chat_id", ""),
        "has_token": bool(config.get("bot_token")),
    }


@router.post("/api/telegram")
async def set_telegram(body: dict = Body(...)):
    config = tool_module._telegram_cfg()
    for key in ("enabled", "bot_token", "chat_id"):
        if key in body and body[key] not in (None, ""):
            config[key] = body[key]
    if body.get("enabled") is False:
        config["enabled"] = False
    db.set_setting("telegram_config", config)
    return {"success": True}


@router.post("/api/telegram/test")
async def test_telegram():
    return await tool_module._send_telegram(
        "✅ Marvin est bien connecté à ce Telegram. Vous recevrez ici vos alertes."
    )


@router.get("/api/learning")
async def learning_list():
    import learning

    return await asyncio.to_thread(_learning_snapshot, learning)


@router.get("/api/learning/recall")
async def learning_recall(q: str):
    import learning

    return await learning.recall(q)


@router.delete("/api/learning/{kind}/{point_id}")
async def learning_delete(kind: Literal["facts", "qa"], point_id: str):
    import learning

    learning.delete_learned("facts" if kind == "facts" else "qa", point_id)
    return {"success": True}


class TeachBody(BaseModel):
    text: str = Field(min_length=4, max_length=4_000)


class LocalModelInstallBody(BaseModel):
    models: list[str] = Field(min_length=1, max_length=10)
    confirmed: bool = False


class LocalPortfolioPolicyBody(BaseModel):
    enabled: bool = True
    auto_download: bool = True
    download_network: Literal["unmetered", "any", "manual"] = "unmetered"
    max_disk_gb: int = Field(default=25, ge=5, le=500)
    min_free_disk_gb: int = Field(default=10, ge=5, le=200)
    maintained_roles: list[str] = Field(default_factory=list, max_length=10)


@router.post("/api/learning/fact")
async def learning_add_fact(body: TeachBody):
    import learning

    await learning.add_fact(body.text)
    return {"success": True}


@router.get("/api/auto-config")
async def get_auto_config():
    config = db.get_setting("auto_config") or {}
    enabled = db.get_setting("auto_model_config")
    config["enabled"] = True if enabled is None else bool(enabled)
    return config


@router.post("/api/auto-config")
async def run_auto_config(body: dict = Body(default={})):
    import auto_config

    if "enabled" in body:
        db.set_setting("auto_model_config", bool(body["enabled"]))
    if "mode" in body:
        mode = body.get("mode") or "auto"
        db.set_setting("perf_mode", mode if mode in auto_config._MODES else "auto")
    return await auto_config.apply_auto_config(force=True)


@router.get("/api/auto-config/models/download")
async def local_model_download_status():
    import local_model_installer

    return local_model_installer.status()


@router.post("/api/auto-config/models/download")
async def local_model_download(body: LocalModelInstallBody):
    import local_model_installer

    try:
        return local_model_installer.start(body.models, confirmed=body.confirmed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/auto-config/models/policy")
async def local_model_policy_status():
    import auto_config
    import local_model_policy
    import local_model_portfolio

    installed = await auto_config._installed_models()
    recommendation = local_model_policy.recommend(
        auto_config.detect_hardware(), installed,
    )
    return local_model_portfolio.evaluate(recommendation)


@router.put("/api/auto-config/models/policy")
async def update_local_model_policy(body: LocalPortfolioPolicyBody):
    import auto_config
    import local_model_installer
    import local_model_policy
    import local_model_portfolio

    previous = local_model_portfolio.get_policy()
    policy = local_model_portfolio.save_policy(body.model_dump())
    try:
        installed = await auto_config._installed_models()
        recommendation = local_model_policy.recommend(auto_config.detect_hardware(), installed)
        evaluation = local_model_portfolio.evaluate(recommendation, policy)
        queue = evaluation["auto_download_queue"]
        download = None
        # Cette écriture est la confirmation explicite de la politique autonome.
        if queue and policy["download_network"] != "manual":
            download = local_model_installer.start(queue, confirmed=True)
        audit.log_action(
            "local_model_portfolio_policy_change",
            {
                "previous_auto_download": bool(previous.get("auto_download")),
                "requested_auto_download": bool(policy.get("auto_download")),
                "maintained_roles": list(policy.get("maintained_roles") or []),
            },
            {
                "success": True,
                "queued_models": len(queue),
                "network_cost": evaluation.get("network_cost"),
            },
            source="ui",
        )
        return {**evaluation, "download": download}
    except Exception:
        local_model_portfolio.save_policy(previous)
        raise


@router.get("/api/perf-modes")
async def list_performance_modes():
    import auto_config

    config = db.get_setting("auto_config") or {}
    return {
        "modes": [
            {
                "key": key,
                **{
                    field: auto_config._MODES[key][field]
                    for field in ("label", "desc", "max_tools", "whisper", "learn", "doc")
                },
            }
            for key in auto_config._MODE_ORDER
        ],
        "active": config.get("mode"),
        "auto": config.get("auto_mode"),
        "is_override": config.get("is_override", False),
        "override_setting": db.get_setting("perf_mode") or "auto",
    }


@router.get("/api/audit")
async def get_audit(limit: int = 100, source: str = ""):
    import audit

    return {
        "actions": audit.recent(limit=limit, source=source or None),
        "stats": audit.stats(),
    }


@router.post("/api/audit/clear")
async def clear_audit(body: dict = Body(default={})):
    import audit

    if body.get("confirmed") is not True:
        return {
            "success": False,
            "requiresConfirmation": True,
            "message": "Confirmer l'effacement du journal d'audit et de ses archives.",
        }
    audit.clear()
    audit.log_action("audit_clear", {}, {"success": True}, source="ui")
    return {"success": True}
