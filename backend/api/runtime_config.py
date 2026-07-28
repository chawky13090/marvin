"""Routes d'apprentissage, configuration matérielle, Telegram et audit."""

from fastapi import APIRouter, Body
from pydantic import BaseModel

import database as db
import tools as tool_module


router = APIRouter(tags=["runtime-config"])


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

    return {
        "counts": learning.count_learned(),
        "facts": learning.list_learned("facts", 200),
        "qa": learning.list_learned("qa", 100),
    }


@router.get("/api/learning/recall")
async def learning_recall(q: str):
    import learning

    return await learning.recall(q)


@router.delete("/api/learning/{kind}/{point_id}")
async def learning_delete(kind: str, point_id: str):
    import learning

    learning.delete_learned("facts" if kind == "facts" else "qa", point_id)
    return {"success": True}


class TeachBody(BaseModel):
    text: str


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
