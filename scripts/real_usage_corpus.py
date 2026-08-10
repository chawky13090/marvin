"""Extraction privée et reproductible des demandes humaines réellement outillées."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CHUNK_SIZE = 48_000
MAX_CHUNKS = 256
PURPOSE_TEXT = "forge-real-usage-text-v1"
PURPOSE_PROVENANCE = "forge-real-usage-provenance-v1"
Protect = Callable[[bytes, str], bytes]
Unprotect = Callable[[bytes, str], bytes]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def protect_payload(value: Any, *, purpose: str, protect: Protect) -> dict[str, Any]:
    raw = _canonical(value)
    if not raw or len(raw) > CHUNK_SIZE * MAX_CHUNKS:
        raise ValueError("Charge de corpus hors limites.")
    chunks = [
        base64.b64encode(protect(raw[offset : offset + CHUNK_SIZE], purpose)).decode("ascii")
        for offset in range(0, len(raw), CHUNK_SIZE)
    ]
    return {
        "schema": "marvin.dpapi-chunked-corpus/1.0",
        "purpose": purpose,
        "plaintext_sha256": hashlib.sha256(raw).hexdigest(),
        "plaintext_bytes": len(raw),
        "chunks": chunks,
    }


def unprotect_payload(value: dict[str, Any], *, unprotect: Unprotect) -> Any:
    chunks = value.get("chunks")
    purpose = str(value.get("purpose") or "")
    if (
        not purpose
        or not isinstance(chunks, list)
        or not chunks
        or len(chunks) > MAX_CHUNKS
    ):
        raise ValueError("Enveloppe de corpus invalide.")
    raw = b"".join(
        unprotect(base64.b64decode(chunk, validate=True), purpose)
        for chunk in chunks
    )
    if len(raw) != int(value.get("plaintext_bytes", -1)):
        raise ValueError("Taille du corpus incohérente.")
    if hashlib.sha256(raw).hexdigest() != value.get("plaintext_sha256"):
        raise ValueError("Empreinte du corpus incohérente.")
    return json.loads(raw.decode("utf-8"))


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def extract(database_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    uri = database_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            WITH linked AS (
              SELECT e.id AS execution_id, e.tool_name, e.args, e.success,
                     e.created_at AS execution_at, e.conversation_id,
                     (
                       SELECT m.id FROM messages AS m
                       WHERE m.conversation_id = e.conversation_id
                         AND m.role = 'user'
                         AND m.created_at <= e.created_at
                       ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1
                     ) AS user_message_id
              FROM tool_executions AS e
              INNER JOIN conversations AS c ON c.id = e.conversation_id
            )
            SELECT m.id AS message_id, m.conversation_id, m.content, m.created_at,
                   l.execution_id, l.tool_name, l.args, l.success, l.execution_at
            FROM linked AS l
            INNER JOIN messages AS m ON m.id = l.user_message_id
            WHERE l.user_message_id IS NOT NULL
            ORDER BY m.created_at ASC, m.id ASC, l.execution_at ASC, l.execution_id ASC
            """
        ).fetchall()
    finally:
        connection.close()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        message_id = str(row["message_id"])
        record = grouped.setdefault(
            message_id,
            {
                "message_id": message_id,
                "conversation_id": str(row["conversation_id"]),
                "created_at": str(row["created_at"]),
                "content": str(row["content"]),
                "executions": [],
            },
        )
        try:
            arguments = json.loads(row["args"] or "{}")
        except json.JSONDecodeError:
            arguments = {}
        record["executions"].append(
            {
                "id": str(row["execution_id"]),
                "tool": str(row["tool_name"]),
                "action": str(arguments.get("action") or "__default__"),
                "success": bool(row["success"]),
                "created_at": str(row["execution_at"]),
            }
        )
    text_records = []
    provenance_records = []
    for ordinal, record in enumerate(grouped.values(), start=1):
        opaque_id = f"real-{ordinal:04d}-{hashlib.sha256(record['message_id'].encode()).hexdigest()[:12]}"
        text_records.append(
            {
                "id": opaque_id,
                "created_at": record["created_at"],
                "text": record["content"],
            }
        )
        provenance_records.append(
            {
                "id": opaque_id,
                "message_id": record["message_id"],
                "conversation_id": record["conversation_id"],
                "executions": record["executions"],
            }
        )
    return text_records, provenance_records


def publish_private_extraction(
    *,
    database_path: Path,
    private_directory: Path,
    public_manifest_path: Path,
    protect: Protect,
    unprotect: Unprotect,
) -> dict[str, Any]:
    texts, provenance = extract(database_path)
    text_envelope = protect_payload(texts, purpose=PURPOSE_TEXT, protect=protect)
    provenance_envelope = protect_payload(
        provenance, purpose=PURPOSE_PROVENANCE, protect=protect
    )
    if unprotect_payload(text_envelope, unprotect=unprotect) != texts:
        raise RuntimeError("Relecture DPAPI du corpus texte incohérente.")
    if unprotect_payload(provenance_envelope, unprotect=unprotect) != provenance:
        raise RuntimeError("Relecture DPAPI de la provenance incohérente.")
    text_path = private_directory / "real-usage-text.dpapi.json"
    provenance_path = private_directory / "real-usage-provenance.dpapi.json"
    _write_atomic(text_path, text_envelope)
    _write_atomic(provenance_path, provenance_envelope)
    manifest = {
        "schema": "marvin.real-usage-private-extraction/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "private_extraction_not_labeled_not_frozen",
        "unit": "distinct_persisted_user_message_with_linked_tool_execution",
        "message_count": len(texts),
        "conversation_count": len({item["conversation_id"] for item in provenance}),
        "text_records_sha256": _digest(texts),
        "provenance_records_sha256": _digest(provenance),
        "privacy": {
            "plaintext_in_public_artifact": False,
            "tool_history_separated_from_labeling_text": True,
            "private_storage": "DPAPI CurrentUser",
            "portable": False,
        },
        "labeling_authorized": False,
        "freeze_authorized": False,
        "limitations": [
            "The historical schema does not identify whether a linked execution was initiated by an automation inside a persisted conversation.",
            "No capability family is inferred from historical tool names.",
            "Texts remain private and must be pseudonymized before any benchmark publication.",
        ],
    }
    _write_atomic(public_manifest_path, manifest)
    return manifest
