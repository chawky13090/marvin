"""API IA et automatisation e-mail avec activation explicitement confirmée."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import database as db
import tool_runtime
import tools as tool_module


router = APIRouter()


class DraftReplyRequest(BaseModel):
    uid: str = ""
    body: str = ""
    subject: str = ""
    from_: str = Field("", alias="from")
    instruction: str = ""
    tone: str = ""
    folder: str = "INBOX"
    account: str = ""
    model_config = {"populate_by_name": True}


class SummarizeRequest(BaseModel):
    uid: str = ""
    body: str = ""
    subject: str = ""
    from_: str = Field("", alias="from")
    folder: str = "INBOX"
    account: str = ""
    model_config = {"populate_by_name": True}


class AutomationConfig(BaseModel):
    mode: str = "manuel"
    accounts: list[str] = Field(default_factory=list)
    instructions: str = ""
    tone: str = "professionnel, clair et courtois"
    signature: str = ""
    only_from: list[str] = Field(default_factory=list)
    never_from: list[str] = Field(default_factory=list)
    skip_keywords: list[str] = Field(default_factory=list)
    max_per_run: int = 5
    send_delay_min: int = 5
    scheduler_enabled: bool = False
    scheduler_confirmed: bool = False
    interval_min: int = 5
    profiles: dict[str, dict] = Field(default_factory=dict)


def _as_dict(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return value if isinstance(value, list) else []


async def _run_tool(name: str, arguments: dict):
    outcome = await tool_runtime.execute(
        name,
        arguments,
        source="email_ui",
        confirmed_by_ui=name == "email_automation_run" and not arguments.get("dry_run"),
    )
    result = outcome.result
    if outcome.status_code != 200:
        detail = result.get("error") if isinstance(result, dict) else "Action e-mail refusée."
        raise HTTPException(status_code=outcome.status_code, detail=detail)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


def _message_args(body: SummarizeRequest) -> dict:
    return {
        "uid": body.uid,
        "body": body.body,
        "subject": body.subject,
        "from": body.from_,
        "folder": body.folder,
        "account": body.account or None,
    }


@router.post("/api/email/draft-reply")
async def email_draft_reply(body: DraftReplyRequest):
    arguments = _message_args(body)
    arguments.update({"instruction": body.instruction, "tone": body.tone})
    return await _run_tool("email_draft_reply", arguments)


@router.post("/api/email/summarize")
async def email_summarize(body: SummarizeRequest):
    return await _run_tool("email_summarize", _message_args(body))


@router.get("/api/email/digest")
async def email_digest(account: str | None = None, limit: int = 15, folder: str = "INBOX"):
    return await _run_tool(
        "email_digest", {"account": account, "limit": limit, "folder": folder}
    )


@router.get("/api/email/automation")
async def get_email_automation():
    config = _as_dict(db.get_setting("email_automation")) or {"mode": "manuel"}
    return {"scheduler_enabled": False, "interval_min": 5, "profiles": {}, **config}


@router.post("/api/email/automation")
async def set_email_automation(body: AutomationConfig):
    previous = _as_dict(db.get_setting("email_automation"))
    was_enabled = bool(previous.get("scheduler_enabled"))
    if body.scheduler_enabled and not was_enabled and not body.scheduler_confirmed:
        raise HTTPException(
            status_code=409,
            detail="Confirmation explicite requise pour activer les envois automatiques en arrière-plan.",
        )
    data = body.model_dump(exclude={"scheduler_confirmed"})
    data["interval_min"] = max(2, min(int(data["interval_min"]), 1440))
    data["max_per_run"] = max(1, min(int(data["max_per_run"]), 100))
    data["send_delay_min"] = max(1, min(int(data["send_delay_min"]), 1440))
    db.set_setting("email_automation", data)
    return {"success": True, "mode": body.mode, "scheduler_enabled": body.scheduler_enabled}


@router.post("/api/email/automation/run")
async def run_email_automation(dry_run: bool = False, mode: str | None = None):
    return await _run_tool(
        "email_automation_run", {"dry_run": dry_run, "mode": mode, "source": "manual"}
    )


@router.get("/api/email/automation/status")
async def email_automation_status():
    config = tool_module._email_automation_cfg()
    history = _as_list(db.get_setting("email_automation_runs"))
    return {
        "scheduler_enabled": config.get("scheduler_enabled", False),
        "interval_min": config.get("interval_min", 5),
        "selected_accounts": config.get("accounts", []),
        "last_run": history[-1] if history else None,
    }


@router.get("/api/email/automation/drafts")
async def get_pending_drafts():
    return {"drafts": _as_list(db.get_setting("email_pending_drafts"))}


@router.post("/api/email/automation/drafts/clear")
async def clear_pending_drafts():
    db.set_setting("email_pending_drafts", [])
    return {"success": True}


@router.get("/api/email/automation/outbox")
async def get_email_automation_outbox():
    return {"outbox": _as_list(db.get_setting("email_scheduled_outbox"))}


@router.delete("/api/email/automation/outbox/{item_id}")
async def cancel_email_automation_outbox(item_id: str):
    outbox = _as_list(db.get_setting("email_scheduled_outbox"))
    remaining = [item for item in outbox if item.get("id") != item_id]
    if len(remaining) == len(outbox):
        raise HTTPException(status_code=404, detail="Envoi différé introuvable")
    db.set_setting("email_scheduled_outbox", remaining)
    return {"success": True, "cancelled": item_id}


@router.post("/api/email/to-task")
async def email_to_task(body: SummarizeRequest):
    return await _run_tool("email_to_task", _message_args(body))


@router.get("/api/email/attachment/summary")
async def email_attachment_summary(
    uid: str, name: str = "", account: str | None = None, folder: str = "INBOX"
):
    return await _run_tool(
        "email_attachment_summary",
        {"uid": uid, "name": name, "account": account, "folder": folder},
    )
