"""API des signatures, modèles, surveillance et règles e-mail."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, HTTPException

import database as db
import tool_runtime


router = APIRouter()


def coerce_object(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return value if value is not None else default


@router.get("/api/email/signatures")
async def get_signatures():
    return {"signatures": coerce_object(db.get_setting("email_signatures"), {})}


@router.post("/api/email/signatures")
async def set_signatures(body: dict = Body(...)):
    signatures = coerce_object(db.get_setting("email_signatures"), {})
    account = str(body.get("account") or "").strip()
    if not account:
        raise HTTPException(status_code=400, detail="account requis")
    signatures[account] = body.get("signature", "")
    db.set_setting("email_signatures", signatures)
    return {"success": True}


@router.get("/api/email/templates")
async def get_templates():
    templates = coerce_object(db.get_setting("email_templates"), [])
    return {"templates": templates if isinstance(templates, list) else []}


@router.post("/api/email/templates")
async def add_template(body: dict = Body(...)):
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="nom requis")
    templates = coerce_object(db.get_setting("email_templates"), [])
    if not isinstance(templates, list):
        templates = []
    templates = [item for item in templates if item.get("name") != name]
    templates.append({"name": name, "body": body.get("body", "")})
    db.set_setting("email_templates", templates[-50:])
    return {"success": True, "count": len(templates)}


@router.delete("/api/email/templates/{name}")
async def delete_template(name: str):
    templates = coerce_object(db.get_setting("email_templates"), [])
    if not isinstance(templates, list):
        templates = []
    remaining = [item for item in templates if item.get("name") != name]
    db.set_setting("email_templates", remaining)
    return {"success": True, "count": len(remaining)}


@router.get("/api/email/watch")
async def get_email_watch():
    return coerce_object(
        db.get_setting("email_watch"),
        {"enabled": False, "interval_min": 5, "accounts": [], "max_notify": 5},
    )


@router.post("/api/email/watch")
async def set_email_watch(body: dict = Body(...)):
    db.set_setting("email_watch", body)
    return {"success": True, "enabled": bool(body.get("enabled"))}


@router.post("/api/email/watch/run")
async def run_email_watch():
    return (
        await tool_runtime.execute(
            "email_watch_check",
            {"force": True},
            source="email_ui",
        )
    ).result


@router.get("/api/email/watch/alerts")
async def get_email_alerts():
    return {"alerts": coerce_object(db.get_setting("email_watch_alerts"), [])}


@router.post("/api/email/watch/alerts/clear")
async def clear_email_alerts():
    db.set_setting("email_watch_alerts", [])
    return {"success": True}


@router.get("/api/email/rules")
async def get_email_rules():
    return {"rules": coerce_object(db.get_setting("email_rules"), [])}


@router.post("/api/email/rules")
async def set_email_rules(body: dict = Body(...)):
    rules = body.get("rules", [])
    stored = rules if isinstance(rules, list) else []
    db.set_setting("email_rules", stored)
    return {"success": True, "count": len(stored)}


@router.post("/api/email/rules/run")
async def run_email_rules(dry_run: bool = False, account: str | None = None):
    return (
        await tool_runtime.execute(
            "email_apply_rules",
            {"dry_run": dry_run, "account": account},
            source="email_ui",
        )
    ).result
