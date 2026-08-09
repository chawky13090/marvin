"""Recus transactionnels pour eviter la double execution des actions d'un tour chat."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import api_observability
from db_connection import db


_PROCESS_TOKEN = uuid.uuid4().hex
_LOGGER = logging.getLogger(__name__)
_ACTION_PARTS = frozenset({
    "apply", "clean", "convert", "copy", "create", "delete", "execute", "fill",
    "generate", "install", "kill", "mark", "merge", "move", "protect", "remove",
    "rename", "reset", "restore", "rotate", "run", "save", "send", "set", "split",
    "start", "stop", "subscribe", "uninstall", "unsubscribe", "update", "upgrade",
    "upload", "write",
})
_GUARDED_EXACT = frozenset({
    "bulk_rename", "code_workspace_control", "email_automation_run", "email_to_task",
    "pc_run_command", "pc_run_elevated", "pc_run_powershell", "ssh_exec",
    "ssh_exec_multi", "ssh_write_and_run", "sqlite_query",
    "windows_task",
})
_SECRET_MARKERS = (
    "password", "token", "secret", "api_key", "apikey", "credential", "private_key",
    "authorization", "cookie",
)


class IdempotencyMismatchError(RuntimeError):
    """Une clé client a été réutilisée pour une opération différente."""


def should_guard(tool_name: str) -> bool:
    """Vrai pour une action susceptible de produire un effet ou un objet externe."""
    normalized = str(tool_name or "").strip().lower()
    if normalized in _GUARDED_EXACT:
        return True
    return bool(set(normalized.split("_")) & _ACTION_PARTS)


def _canonical_args(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def idempotency_key(
    request_id: str,
    conversation_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    client_key: str | None = None,
) -> tuple[str, str]:
    canonical = _canonical_args(arguments)
    args_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    payload = (
        f"http\0{client_key}".encode("utf-8")
        if client_key
        else "\0".join(
            (request_id, conversation_id, tool_name, args_hash)
        ).encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest(), args_hash


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[MASQUE]" if any(marker in str(key).lower() for marker in _SECRET_MARKERS)
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _with_replay(result: Any, **metadata: Any) -> Any:
    if not isinstance(result, dict):
        return result
    enriched = dict(result)
    enriched["_replay"] = metadata
    return enriched


def claim(
    *,
    request_id: str,
    conversation_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    client_key: str | None = None,
) -> dict[str, Any]:
    """Reserve atomiquement une action ou retourne son etat durable existant."""
    key, args_hash = idempotency_key(
        request_id,
        conversation_id,
        tool_name,
        arguments,
        client_key=client_key,
    )
    with db() as connection:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO action_receipts
               (idempotency_key, request_id, conversation_id, tool_name, args_hash, status, owner_token)
               VALUES (?, ?, ?, ?, ?, 'started', ?)""",
            (key, request_id, conversation_id, tool_name, args_hash, _PROCESS_TOKEN),
        )
        if cursor.rowcount == 1:
            return {"state": "execute", "key": key}
        row = connection.execute(
            "SELECT status, owner_token, result_json FROM action_receipts WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Le recu d'action est introuvable apres reservation.")
        if client_key:
            identity = connection.execute(
                """SELECT conversation_id, tool_name, args_hash
                   FROM action_receipts WHERE idempotency_key = ?""",
                (key,),
            ).fetchone()
            if identity is None or (
                str(identity["conversation_id"]) != conversation_id
                or str(identity["tool_name"]) != tool_name
                or str(identity["args_hash"]) != args_hash
            ):
                api_observability.record_idempotency_decision("mismatch")
                raise IdempotencyMismatchError(
                    "Cette clé d'idempotence appartient à une autre opération."
                )
        status = str(row["status"])
        if status == "completed":
            try:
                result = json.loads(row["result_json"] or "null")
            except (TypeError, json.JSONDecodeError):
                result = {"success": False, "error": "Recu termine illisible."}
            return {"state": "completed", "key": key, "result": result}
        if status == "started" and row["owner_token"] == _PROCESS_TOKEN:
            return {"state": "in_progress", "key": key}
        if status == "started":
            connection.execute(
                "UPDATE action_receipts SET status = 'unknown' WHERE idempotency_key = ?",
                (key,),
            )
        return {"state": "unknown", "key": key}


def complete(key: str, result: Any) -> None:
    safe_result = _redact(result)
    payload = json.dumps(safe_result, ensure_ascii=False, default=str)
    with db() as connection:
        cursor = connection.execute(
            """UPDATE action_receipts
               SET status = 'completed', result_json = ?, completed_at = datetime('now')
               WHERE idempotency_key = ? AND status = 'started' AND owner_token = ?""",
            (payload, key, _PROCESS_TOKEN),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Le recu d'action ne peut pas etre finalise par ce processus.")


def mark_unknown(key: str) -> None:
    """Ferme un reçu dont l'effet peut avoir eu lieu avant une exception."""
    with db() as connection:
        connection.execute(
            """UPDATE action_receipts SET status = 'unknown'
               WHERE idempotency_key = ? AND status = 'started' AND owner_token = ?""",
            (key, _PROCESS_TOKEN),
        )


async def execute_once(
    *,
    request_id: str | None,
    conversation_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    operation: Callable[[], Awaitable[Any]],
    guarded: bool | None = None,
    client_key: str | None = None,
) -> Any:
    """Execute une action une fois; rejoue son recu sans reproduire l'effet externe."""
    guarded_action = should_guard(tool_name) if guarded is None else guarded
    if not request_id or (not client_key and not guarded_action):
        return await operation()

    receipt = claim(
        request_id=request_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        arguments=arguments,
        client_key=client_key,
    )
    state = receipt["state"]
    key = receipt["key"]
    if state == "completed":
        api_observability.record_idempotency_decision("replayed")
        return _with_replay(receipt["result"], reused=True, state=state, key=key)
    if state == "in_progress":
        api_observability.record_idempotency_decision("in_progress")
        return {
            "success": False,
            "error": "Cette action est deja en cours pour cette demande; elle n'a pas ete relancee.",
            "action_in_progress": True,
            "_replay": {"reused": False, "state": state, "key": key},
        }
    if state == "unknown":
        api_observability.record_idempotency_decision("unknown")
        return {
            "success": False,
            "error": (
                "Le backend a ete interrompu pendant cette action. Son resultat est inconnu; "
                "Marvin refuse de la rejouer automatiquement pour eviter un doublon."
            ),
            "action_outcome_unknown": True,
            "_replay": {"reused": False, "state": state, "key": key},
        }

    try:
        result = await operation()
    except BaseException:
        mark_unknown(key)
        api_observability.record_idempotency_decision("unknown")
        raise
    try:
        complete(key, result)
    except Exception as exc:
        # L'action a deja eu lieu : ne jamais masquer son resultat ni tenter un second
        # passage parce que la persistance du recu a echoue apres coup.
        incident = uuid.uuid4().hex
        _LOGGER.warning(
            "action_receipt_persistence_failure error_type=%s incident=%s",
            type(exc).__name__,
            incident,
        )
        api_observability.record_idempotency_decision("receipt_error")
        return _with_replay(
            result,
            reused=False,
            state="receipt_error",
            key=key,
            receipt_persisted=False,
            warning=f"Le reçu n'a pas pu être persisté. Incident : {incident}.",
            incident=incident,
        )
    api_observability.record_idempotency_decision("completed")
    return _with_replay(result, reused=False, state="completed", key=key, receipt_persisted=True)
