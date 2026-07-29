"""Routes des événements locaux/Google et des abonnements iCal."""

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

import tool_runtime
from http_idempotency import IDEMPOTENCY_RESPONSES, IdempotencyKey, execute as execute_idempotent


router = APIRouter(tags=["calendar"])


async def _calendar_tool(
    name: str,
    arguments: dict,
    *,
    confirmed_by_ui: bool = False,
):
    outcome = await tool_runtime.execute(
        name,
        arguments,
        source="calendar_ui",
        confirmed_by_ui=confirmed_by_ui,
    )
    if outcome.status_code != 200:
        detail = (
            outcome.result.get("error")
            if isinstance(outcome.result, dict)
            else "Outil agenda refusé."
        )
        raise HTTPException(status_code=outcome.status_code, detail=detail)
    return outcome.result


@router.get("/api/events")
async def list_events(
    period: str = "", start: str = "", end: str = "", limit: int = 200
):
    args = {}
    if period:
        args["period"] = period
    if start:
        args["start"] = start
    if end:
        args["end"] = end
    args["limit"] = limit
    return await _calendar_tool("event_list", args)


class EventBody(BaseModel):
    title: str = ""
    natural: str = ""
    start_at: str = ""
    end_at: str = ""
    location: str = ""
    description: str = ""
    all_day: bool = False
    reminder_minutes: int | None = None
    local_only: bool = False


@router.post("/api/events", responses=IDEMPOTENCY_RESPONSES)
async def create_event(body: EventBody, idempotency_key: IdempotencyKey = None):
    async def create_once():
        result = await _calendar_tool("event_create", body.model_dump())
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result

    return await execute_idempotent(
        operation_name="http_event_create",
        payload=body.model_dump(),
        operation=create_once,
        idempotency_key=idempotency_key,
    )


@router.patch("/api/events/{event_id}")
async def update_event(event_id: str, body: dict = Body(...)):
    body["id"] = event_id
    result = await _calendar_tool("event_update", body)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/api/events/{event_id}")
async def delete_event(event_id: str):
    # La requête DELETE provient du geste explicite de l'interface. Les appels du LLM
    # continuent à recevoir une demande de confirmation avant toute suppression.
    return await _calendar_tool(
        "event_delete",
        {"id": event_id},
        confirmed_by_ui=True,
    )


@router.get("/api/calendar/subscriptions")
async def list_calendar_subscriptions():
    return await _calendar_tool("calendar_subscriptions", {})


class CalendarSubscriptionBody(BaseModel):
    url: str
    name: str = ""
    color: str = "#10b981"


@router.post("/api/calendar/subscriptions")
async def add_calendar_subscription(body: CalendarSubscriptionBody):
    result = await _calendar_tool("calendar_subscribe", body.model_dump())
    if result.get("error") and not result.get("subscription"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/api/calendar/subscriptions/{subscription_id}")
async def remove_calendar_subscription(subscription_id: str):
    # Le clic explicite sur la route DELETE constitue la confirmation UI. Les appels LLM
    # restent soumis à la demande de confirmation du domaine.
    return await _calendar_tool(
        "calendar_unsubscribe",
        {"id": subscription_id, "confirmed": True},
        confirmed_by_ui=True,
    )


@router.post("/api/calendar/subscriptions/sync")
async def sync_calendar_subscriptions(subscription_id: str = ""):
    args = {"id": subscription_id} if subscription_id else {}
    return await _calendar_tool("calendar_sync", args)
