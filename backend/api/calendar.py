"""Routes des événements locaux/Google et des abonnements iCal."""

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

import tools as tool_module


router = APIRouter(tags=["calendar"])


@router.get("/api/events")
async def list_events(period: str = "", start: str = "", end: str = ""):
    args = {}
    if period:
        args["period"] = period
    if start:
        args["start"] = start
    if end:
        args["end"] = end
    return await tool_module.TOOLS_REGISTRY["event_list"](args)


class EventBody(BaseModel):
    title: str = ""
    natural: str = ""
    start_at: str = ""
    end_at: str = ""
    location: str = ""
    description: str = ""
    all_day: bool = False
    reminder_minutes: int | None = None


@router.post("/api/events")
async def create_event(body: EventBody):
    result = await tool_module.TOOLS_REGISTRY["event_create"](body.model_dump())
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.patch("/api/events/{event_id}")
async def update_event(event_id: str, body: dict = Body(...)):
    body["id"] = event_id
    result = await tool_module.TOOLS_REGISTRY["event_update"](body)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/api/events/{event_id}")
async def delete_event(event_id: str):
    return await tool_module.TOOLS_REGISTRY["event_delete"]({"id": event_id})


@router.get("/api/calendar/subscriptions")
async def list_calendar_subscriptions():
    return await tool_module.TOOLS_REGISTRY["calendar_subscriptions"]({})


class CalendarSubscriptionBody(BaseModel):
    url: str
    name: str = ""
    color: str = "#10b981"


@router.post("/api/calendar/subscriptions")
async def add_calendar_subscription(body: CalendarSubscriptionBody):
    result = await tool_module.TOOLS_REGISTRY["calendar_subscribe"](body.model_dump())
    if result.get("error") and not result.get("subscription"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/api/calendar/subscriptions/{subscription_id}")
async def remove_calendar_subscription(subscription_id: str):
    return await tool_module.TOOLS_REGISTRY["calendar_unsubscribe"]({"id": subscription_id})


@router.post("/api/calendar/subscriptions/sync")
async def sync_calendar_subscriptions(subscription_id: str = ""):
    args = {"id": subscription_id} if subscription_id else {}
    return await tool_module.TOOLS_REGISTRY["calendar_sync"](args)
