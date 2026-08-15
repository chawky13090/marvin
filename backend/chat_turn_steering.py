"""Pilotage durable d'un tour agentique, sans exposer le texte dans les logs."""

from __future__ import annotations

import json
from typing import Any

import database
from db_connection import db
from repositories.chat_turn_directives import ChatTurnDirectiveRepository
from repositories import tool_approvals


repository = ChatTurnDirectiveRepository(db)
connection_scope = db


def enabled() -> bool:
    return database.get_setting("chat_turn_steering_enabled") is True


def reserve(conversation_key: str, root_request_id: str, conversation_id: str = "") -> dict:
    return repository.reserve_slot(
        conversation_key=conversation_key,
        root_request_id=root_request_id,
        conversation_id=conversation_id,
    )


def release(root_request_id: str) -> bool:
    with connection_scope() as connection:
        return connection.execute(
            "DELETE FROM chat_turn_slots WHERE root_request_id = ?", (root_request_id,)
        ).rowcount == 1


def rebind(root_request_id: str, provisional_key: str, conversation_id: str) -> dict:
    return repository.rebind_slot(
        provisional_key=provisional_key,
        conversation_key=conversation_id,
        conversation_id=conversation_id,
        root_request_id=root_request_id,
    )


def active(conversation_key: str) -> dict | None:
    with connection_scope() as connection:
        row = connection.execute(
            "SELECT * FROM chat_turn_slots WHERE conversation_key = ?", (conversation_key,)
        ).fetchone()
    return dict(row) if row is not None else None


def create(root_request_id: str, client_directive_id: str, kind: str, text: str) -> tuple[dict, bool]:
    row, created = repository.create_directive(
        root_request_id=root_request_id,
        client_directive_id=client_directive_id,
        kind=kind,
        text=text,
    )
    if created and kind in {"append", "redirect"}:
        tool_approvals.invalidate_pending_for_request(
            root_request_id, reason="directive_payload_changed"
        )
    return public(row), created


def cancel(root_request_id: str, directive_id: str) -> dict:
    rows = repository.list_for_turn(root_request_id)
    if not any(str(row["id"]) == directive_id for row in rows):
        raise ValueError("Directive étrangère à ce tour.")
    return public(repository.cancel(directive_id))


def list_public(root_request_id: str) -> list[dict]:
    return [public(row) for row in repository.list_for_turn(root_request_id)]


def public(row: dict) -> dict:
    waiting = row.get("waiting_for_json")
    return {
        "id": row["id"],
        "clientDirectiveId": row["client_directive_id"],
        "rootRequestId": row["root_request_id"],
        "sequence": row["sequence"],
        "kind": row["kind"],
        "text": row["directive_text"],
        "status": row["status"],
        "waitingFor": json.loads(waiting) if waiting else None,
        "reasonCode": row.get("reason_code") or "",
        "createdAt": row["created_at"],
    }


def checkpoint(root_request_id: str, *, phase: str) -> tuple[list[dict[str, Any]], bool]:
    """Applique append/redirect au prochain prompt et signale un arrêt."""
    applied: list[dict[str, Any]] = []
    should_stop = False
    for row in repository.list_for_turn(root_request_id):
        if row["status"] not in {"received", "deferred"}:
            continue
        if row["kind"] == "next":
            if row["status"] == "received":
                repository.transition(
                    row["id"], expected_status="received", target_status="deferred",
                    waiting_for={"kind": "root_turn_terminal"}, reason_code="wait_root_terminal",
                )
            continue
        source = str(row["status"])
        updated = repository.transition(
            row["id"], expected_status=source, target_status="applied",
            reason_code=f"checkpoint:{phase}",
        )
        event = public(updated)
        applied.append(event)
        if row["kind"] == "stop":
            should_stop = True
    return applied, should_stop
