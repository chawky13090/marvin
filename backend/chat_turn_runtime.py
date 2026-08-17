"""Execution et journal SSE durables des tours de conversation Marvin."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from db_connection import db
import bug_log


_PROCESS_TOKEN = uuid.uuid4().hex
_LOGGER = logging.getLogger(__name__)
_TASKS: dict[str, asyncio.Task] = {}
_LOCK = asyncio.Lock()
_TERMINAL = frozenset({"completed", "failed", "interrupted"})


def _has_live_pending_approval(connection, root_request_id: str) -> bool:
    """Vérifie qu'un arrêt ``pending_confirmation`` possède une vraie action UI.

    Le texte ou le ``stopReason`` émis par le modèle ne constitue jamais une
    approbation. Seul un reçu persistant, non expiré et lié au tour racine peut
    conserver l'exclusion mutuelle de la conversation.
    """
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tool_approval_requests'"
    ).fetchone()
    if table is None:
        return False
    return connection.execute(
        """SELECT 1 FROM tool_approval_requests
           WHERE request_id = ? AND status = 'pending' AND expires_at > ?
           LIMIT 1""",
        (str(root_request_id), time.time()),
    ).fetchone() is not None


def payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recover_orphaned_turns() -> int:
    """Marque au demarrage les producteurs perdus, sans rejouer leurs actions."""
    message = "Le backend a redemarre pendant ce tour; reprise automatique refusee sans preuve complete."
    recovered = 0
    with db() as connection:
        rows = connection.execute(
            "SELECT request_id FROM chat_turns WHERE status = 'running' AND owner_token <> ?",
            (_PROCESS_TOKEN,),
        ).fetchall()
        for row in rows:
            request_id = str(row["request_id"])
            next_sequence = int(connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM chat_turn_events WHERE request_id = ?",
                (request_id,),
            ).fetchone()[0])
            connection.execute(
                "INSERT INTO chat_turn_events (request_id, sequence, event_json) VALUES (?, ?, ?)",
                (
                    request_id,
                    next_sequence,
                    json.dumps({"type": "error", "message": message, "turnInterrupted": True}),
                ),
            )
            connection.execute(
                """UPDATE chat_turns SET status = 'interrupted', error = ?,
                   updated_at = datetime('now'), completed_at = datetime('now')
                   WHERE request_id = ?""",
                (message, request_id),
            )
            recovered += 1
        slot_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chat_turn_slots'"
        ).fetchone()
        if slot_table is not None:
            slots = connection.execute(
                "SELECT conversation_key, root_request_id FROM chat_turn_slots"
            ).fetchall()
            for slot in slots:
                root_request_id = str(slot["root_request_id"])
                turn = connection.execute(
                    "SELECT status, owner_token FROM chat_turns WHERE request_id = ?",
                    (root_request_id,),
                ).fetchone()
                owned_running = (
                    turn is not None
                    and str(turn["status"]) == "running"
                    and str(turn["owner_token"]) == _PROCESS_TOKEN
                )
                if owned_running or _has_live_pending_approval(connection, root_request_id):
                    continue
                connection.execute(
                    "DELETE FROM chat_turn_slots WHERE conversation_key = ? AND root_request_id = ?",
                    (str(slot["conversation_key"]), root_request_id),
                )
    return recovered


def prune(retention_days: int = 30) -> int:
    """Supprime uniquement les journaux terminaux anciens; les messages restent intacts."""
    days = max(1, min(int(retention_days), 365))
    with db() as connection:
        cursor = connection.execute(
            """DELETE FROM chat_turns
               WHERE status IN ('completed', 'failed', 'interrupted')
               AND updated_at < datetime('now', ?)""",
            (f"-{days} days",),
        )
        return max(0, int(cursor.rowcount))


def incomplete_tool_calls(conversation_id: str) -> dict[str, dict[str, str]]:
    """Projette les appels sans tool_end d'un tour terminal comme erreurs durables."""
    normalized = str(conversation_id or "").strip()
    if not normalized:
        return {}
    starts: dict[str, dict[str, str]] = {}
    completed: set[str] = set()
    terminal_status: dict[str, str] = {}
    with db() as connection:
        rows = connection.execute(
            """SELECT turn.request_id, turn.status, event.event_json
               FROM chat_turns AS turn
               JOIN chat_turn_events AS event
                 ON event.request_id = turn.request_id
               WHERE turn.conversation_id = ?
                 AND turn.status IN ('completed','failed','interrupted')
               ORDER BY turn.created_at ASC, event.sequence ASC""",
            (normalized,),
        ).fetchall()
    for row in rows:
        try:
            event = json.loads(row["event_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        call_id = str(event.get("toolCallId") or "")
        if not call_id:
            continue
        terminal_status[call_id] = str(row["status"])
        if event.get("type") == "tool_start":
            starts[call_id] = {
                "toolName": str(event.get("toolName") or ""),
            }
        elif event.get("type") == "tool_end":
            completed.add(call_id)
    return {
        call_id: {
            **value,
            "state": "error",
            "error": (
                "Appel interrompu avant la persistance de son résultat."
                if terminal_status.get(call_id) == "interrupted"
                else "Appel terminé sans résultat durable; relance automatique refusée."
            ),
        }
        for call_id, value in starts.items()
        if call_id not in completed
    }


def _decode_agent_chunk(chunk: str) -> dict[str, Any]:
    for line in str(chunk).splitlines():
        if line.startswith("data: "):
            value = json.loads(line[6:].strip())
            if isinstance(value, dict):
                return value
    raise ValueError("Evenement SSE agent invalide.")


def _encode_event(event: dict[str, Any], sequence: int) -> str:
    enriched = dict(event)
    enriched["turnSeq"] = sequence
    return f"id: {sequence}\ndata: {json.dumps(enriched, ensure_ascii=False, default=str)}\n\n"


def _append_event(request_id: str, event: dict[str, Any]) -> int:
    with db() as connection:
        # Sérialise l'allocation MAX(sequence)+1 entre le producteur, une reprise
        # et une interruption. Sans verrou d'écriture acquis avant le SELECT,
        # deux connexions pouvaient choisir la même séquence puis provoquer une
        # IntegrityError sur la clé primaire (request_id, sequence).
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM chat_turn_events WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        sequence = int(row["next_sequence"])
        cursor = connection.execute(
            """INSERT INTO chat_turn_events (request_id, sequence, event_json)
               SELECT ?, ?, ?
               WHERE EXISTS (
                   SELECT 1 FROM chat_turns WHERE request_id = ?
               )""",
            (
                request_id,
                sequence,
                json.dumps(event, ensure_ascii=False, default=str),
                request_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Le tour parent est absent; événement SSE refusé.")
        conversation_id = event.get("conversationId") if event.get("type") == "conv_id" else None
        if conversation_id:
            connection.execute(
                """UPDATE chat_turns SET conversation_id = ?, updated_at = datetime('now')
                   WHERE request_id = ?""",
                (str(conversation_id), request_id),
            )
        else:
            connection.execute(
                "UPDATE chat_turns SET updated_at = datetime('now') WHERE request_id = ?",
                (request_id,),
            )
    return sequence


def _finish(request_id: str, status: str, error: str | None = None) -> None:
    if status not in _TERMINAL:
        raise ValueError("Statut terminal de tour invalide.")
    with db() as connection:
        connection.execute(
            """UPDATE chat_turns
               SET status = ?, error = ?, updated_at = datetime('now'), completed_at = datetime('now')
               WHERE request_id = ? AND owner_token = ?""",
            (status, error, request_id, _PROCESS_TOKEN),
        )


def _record_producer_failure(
    request_id: str,
    *,
    incident: str,
    error_type: str,
    message: str,
) -> None:
    """Termine le tour même si le journal technique est momentanément indisponible."""
    try:
        bug_log.log_bug(
            "chat_turn_producer_failure",
            "Le producteur SSE d'un tour a échoué.",
            context={
                "error_type": error_type,
                "incident": incident,
                "request_hash": hashlib.sha256(
                    request_id.encode("utf-8")
                ).hexdigest()[:16],
            },
        )
    except Exception as log_error:
        # Repli sans message brut : le journal technique ne doit pas bloquer la clôture métier.
        _LOGGER.warning(
            "chat_turn_failure_log_unavailable error_type=%s incident=%s",
            type(log_error).__name__,
            incident,
        )

    try:
        _append_event(
            request_id,
            {
                "type": "error",
                "message": message,
                "incident": incident,
            },
        )
    finally:
        _finish(request_id, "failed", message)


async def _produce(
    request_id: str,
    producer: AsyncIterator[str],
    *,
    steering_root_request_id: str | None = None,
    conversation_key: str = "",
) -> None:
    saw_terminal_event = False
    failed = False
    keep_slot_for_approval = False
    try:
        async for chunk in producer:
            event = _decode_agent_chunk(chunk)
            # Les tâches « ensuite » doivent précéder l'événement terminal dans le
            # journal. Le client peut ainsi les mémoriser avant de recevoir ``done``
            # et démarrer le nouveau tour sans course entre deux événements SSE.
            if event.get("type") == "done":
                if event.get("stopReason") == "pending_confirmation" and steering_root_request_id:
                    with db() as connection:
                        keep_slot_for_approval = _has_live_pending_approval(
                            connection, steering_root_request_id
                        )
                if steering_root_request_id and not keep_slot_for_approval:
                    import chat_turn_steering
                    if chat_turn_steering.enabled():
                        for directive in chat_turn_steering.terminal(steering_root_request_id):
                            _append_event(request_id, {
                                "type": "directive_ready",
                                "directive": directive,
                            })
            _append_event(request_id, event)
            if (
                steering_root_request_id
                and conversation_key
                and event.get("type") == "conv_id"
                and event.get("conversationId")
            ):
                import chat_turn_steering
                if chat_turn_steering.enabled() and conversation_key != event["conversationId"]:
                    chat_turn_steering.rebind(
                        steering_root_request_id,
                        conversation_key,
                        str(event["conversationId"]),
                    )
                    conversation_key = str(event["conversationId"])
            if event.get("type") in {"done", "error"}:
                saw_terminal_event = True
            if event.get("type") == "error":
                failed = True
        if not saw_terminal_event:
            _append_event(request_id, {"type": "done"})
        _finish(request_id, "failed" if failed else "completed")
    except asyncio.CancelledError:
        message = "Le backend s'est arrete pendant ce tour; aucune action ambiguë ne sera rejouee automatiquement."
        _append_event(request_id, {"type": "error", "message": message, "turnInterrupted": True})
        _finish(request_id, "interrupted", message)
        raise
    except Exception as exc:
        incident = uuid.uuid4().hex
        message = (
            "Le tour a été interrompu par une erreur interne. "
            f"Incident : {incident}."
        )
        _record_producer_failure(
            request_id,
            incident=incident,
            error_type=type(exc).__name__,
            message=message,
        )
    finally:
        if steering_root_request_id and not keep_slot_for_approval:
            import chat_turn_steering
            if chat_turn_steering.enabled():
                chat_turn_steering.release(steering_root_request_id)


def _task_finished(request_id: str, task: asyncio.Task) -> None:
    if _TASKS.get(request_id) is task:
        _TASKS.pop(request_id, None)


async def _ensure_started(
    request_id: str,
    fingerprint: str,
    conversation_id: str | None,
    producer_factory: Callable[[], AsyncIterator[str]],
    *,
    conversation_key: str = "",
    root_request_id: str | None = None,
    continuation: bool = False,
) -> str:
    async with _LOCK:
        steering_root = root_request_id or request_id
        with db() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO chat_turns
                   (request_id, payload_hash, conversation_id, status, owner_token)
                   VALUES (?, ?, ?, 'running', ?)""",
                (request_id, fingerprint, conversation_id, _PROCESS_TOKEN),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                "SELECT payload_hash, status, owner_token FROM chat_turns WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Le tour de chat est introuvable apres reservation.")
            if row["payload_hash"] != fingerprint:
                raise ValueError("Ce requestId est deja associe a une autre demande.")
            status = str(row["status"])
            if status == "running" and row["owner_token"] != _PROCESS_TOKEN:
                message = "Le backend a redemarre pendant ce tour; reprise automatique refusee sans preuve complete."
                next_sequence = int(connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM chat_turn_events WHERE request_id = ?",
                    (request_id,),
                ).fetchone()[0])
                connection.execute(
                    "INSERT INTO chat_turn_events (request_id, sequence, event_json) VALUES (?, ?, ?)",
                    (
                        request_id,
                        next_sequence,
                        json.dumps({"type": "error", "message": message, "turnInterrupted": True}),
                    ),
                )
                connection.execute(
                    """UPDATE chat_turns SET status = 'interrupted', error = ?,
                       updated_at = datetime('now'), completed_at = datetime('now')
                       WHERE request_id = ?""",
                    (message, request_id),
                )
                status = "interrupted"

        if status == "running" and steering_root:
            import chat_turn_steering
            if chat_turn_steering.enabled():
                if not conversation_key:
                    message = "Une clé de conversation UUID est requise pour ce tour."
                    if created:
                        _append_event(request_id, {"type": "error", "message": message})
                        _finish(request_id, "failed", message)
                        return "failed"
                    raise ValueError(message)
                try:
                    chat_turn_steering.reserve(
                        conversation_key,
                        steering_root,
                        conversation_id or "",
                    )
                except Exception as exc:
                    from repositories.chat_turn_directives import ConversationBusyError

                    if not isinstance(exc, ConversationBusyError) or not created:
                        raise
                    message = (
                        "Cette conversation traite déjà une demande. "
                        "Votre nouveau message n'a pas été lancé; utilisez le pilotage ou attendez la fin du tour."
                    )
                    _append_event(
                        request_id,
                        {
                            "type": "error",
                            "code": "conversation_busy",
                            "message": message,
                            "retryable": True,
                        },
                    )
                    _finish(request_id, "failed", message)
                    return "failed"

        if created:
            task = asyncio.create_task(_produce(
                request_id,
                producer_factory(),
                steering_root_request_id=steering_root if root_request_id else None,
                conversation_key=conversation_key,
            ))
            _TASKS[request_id] = task
            task.add_done_callback(lambda done, rid=request_id: _task_finished(rid, done))
        return status


def _read_events(request_id: str, after_sequence: int) -> tuple[list[tuple[int, dict]], str]:
    with db() as connection:
        rows = connection.execute(
            """SELECT sequence, event_json FROM chat_turn_events
               WHERE request_id = ? AND sequence > ? ORDER BY sequence ASC LIMIT 250""",
            (request_id, after_sequence),
        ).fetchall()
        turn = connection.execute(
            "SELECT status FROM chat_turns WHERE request_id = ?", (request_id,)
        ).fetchone()
    events = [(int(row["sequence"]), json.loads(row["event_json"])) for row in rows]
    return events, str(turn["status"] if turn else "failed")


async def subscribe(
    *,
    request_id: str,
    fingerprint: str,
    conversation_id: str | None,
    conversation_key: str = "",
    root_request_id: str | None = None,
    continuation: bool = False,
    producer_factory: Callable[[], AsyncIterator[str]],
    after_sequence: int = 0,
) -> AsyncIterator[str]:
    """Demarre un tour une fois et diffuse son journal, meme apres reconnexion UI."""
    status = await _ensure_started(
        request_id,
        fingerprint,
        conversation_id,
        producer_factory,
        conversation_key=conversation_key,
        root_request_id=root_request_id,
        continuation=continuation,
    )
    cursor = max(0, int(after_sequence))
    while True:
        events, status = _read_events(request_id, cursor)
        for sequence, event in events:
            cursor = sequence
            yield _encode_event(event, sequence)
        if status in _TERMINAL and not events:
            return
        await asyncio.sleep(0.08)


async def shutdown() -> None:
    """Arrete proprement les producteurs; leurs tours deviennent explicitement interrompus."""
    tasks = list(_TASKS.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
