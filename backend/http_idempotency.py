"""Adaptateur HTTP borné vers les reçus transactionnels d'actions."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

import action_replay
import api_observability


IdempotencyKey = Annotated[
    uuid.UUID | None,
    Header(
        alias="Idempotency-Key",
        description="UUID stable à réutiliser uniquement pour la même mutation.",
    ),
]

IDEMPOTENCY_RESPONSES = {
    409: {"description": "Mutation identique en cours ou résultat externe inconnu."},
    422: {"description": "Clé réutilisée avec une autre mutation ou charge utile."},
}


async def execute(
    *,
    operation_name: str,
    payload: dict[str, Any],
    operation: Callable[[], Awaitable[dict[str, Any]]],
    idempotency_key: uuid.UUID | None,
    success_status: int = 200,
) -> dict[str, Any] | JSONResponse:
    """Exécute une mutation une fois lorsque le client fournit une clé."""
    if idempotency_key is None:
        return await operation()
    try:
        result = await action_replay.execute_once(
            request_id=api_observability.current_request_id() or uuid.uuid4().hex,
            conversation_id=f"http:{operation_name}",
            tool_name=operation_name,
            arguments=payload,
            operation=operation,
            guarded=True,
            client_key=str(idempotency_key),
        )
    except action_replay.IdempotencyMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail="Cette clé d'idempotence appartient à une autre mutation.",
        ) from exc
    replay = result.get("_replay") if isinstance(result, dict) else None
    if isinstance(replay, dict) and replay.get("state") in {"in_progress", "unknown"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cette mutation est déjà en cours ou son résultat externe est inconnu; "
                "elle n'a pas été relancée."
            ),
        )
    body = dict(result)
    body.pop("_replay", None)
    return JSONResponse(
        status_code=success_status,
        content=jsonable_encoder(body),
        headers={
            "Idempotency-Replayed": (
                "true" if isinstance(replay, dict) and replay.get("reused") is True else "false"
            )
        },
    )
