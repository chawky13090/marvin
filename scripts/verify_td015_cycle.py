"""Vérifie un cycle TD-015 sans importer ni exécuter le backend Marvin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "benchmarks" / "conversation-history" / "td015-closure-policy.json"
DEFAULT_DATABASE = ROOT / "data" / "secretary.db"
BACKEND = "http://127.0.0.1:8005"
FRONTEND = "http://127.0.0.1:3000"


def _get(url: str, timeout: float = 60.0) -> tuple[int, bytes, int]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = response.read()
            return response.status, payload, round((time.monotonic() - started) * 1000)
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, payload, round((time.monotonic() - started) * 1000)


def _json_get(url: str, timeout: float = 60.0) -> tuple[int, dict[str, Any], int, int]:
    status, raw, duration_ms = _get(url, timeout)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Réponse JSON invalide pour {url}: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Objet JSON attendu pour {url}.")
    return status, payload, duration_ms, len(raw)


def _select_target(database: Path, minimum_bytes: int) -> tuple[str, int]:
    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        row = connection.execute(
            """SELECT conversation_id,
                      SUM(LENGTH(COALESCE(content, '')) + LENGTH(COALESCE(tool_results, ''))) AS stored_bytes
               FROM messages
               GROUP BY conversation_id
               ORDER BY stored_bytes DESC
               LIMIT 1"""
        ).fetchone()
    finally:
        connection.close()
    if not row or not row[0] or int(row[1] or 0) < minimum_bytes:
        raise RuntimeError("Aucune conversation historique ne satisfait le volume pré-enregistré.")
    return str(row[0]), int(row[1])


def validate_page_chain(pages: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    """Valide la continuité observable d'une suite de pages par curseur."""
    if len(pages) < int(policy["minimum_pages"]):
        raise RuntimeError("Nombre de pages inférieur au minimum pré-enregistré.")
    all_ids: list[str] = []
    cursors: list[int] = []
    for page in pages:
        message_ids = [str(item.get("id") or "") for item in page["messages"]]
        if not message_ids or any(not item for item in message_ids):
            raise RuntimeError("Une page contient un identifiant de message vide.")
        all_ids.extend(message_ids)
        cursor = page["page"].get("nextBeforeRowid")
        if cursor is not None:
            cursors.append(int(cursor))
        if page["page"].get("cutoffReason") not in policy["allowed_cutoff_reasons"]:
            raise RuntimeError("Raison de coupure hors contrat.")
    duplicate_count = len(all_ids) - len(set(all_ids))
    if duplicate_count != int(policy["duplicate_message_ids_allowed"]):
        raise RuntimeError(f"Doublons de messages observés: {duplicate_count}.")
    if len(all_ids) < int(policy["minimum_unique_display_messages"]):
        raise RuntimeError("Couverture de l'historique lourd insuffisante.")
    if policy["cursor_must_strictly_decrease"]:
        if any(current >= previous for previous, current in zip(cursors, cursors[1:])):
            raise RuntimeError("Le curseur historique ne décroît pas strictement.")
    if bool(pages[-1]["page"].get("hasOlderRows")) != bool(policy["final_has_older_rows"]):
        raise RuntimeError("La dernière page n'épuise pas l'historique attendu.")
    return {
        "pages": len(pages),
        "unique_display_messages": len(set(all_ids)),
        "duplicate_message_ids": duplicate_count,
        "cursor_strictly_decreasing": True,
        "final_has_older_rows": bool(pages[-1]["page"].get("hasOlderRows")),
    }


def _collect_pages(conversation_id: str, policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[int]]:
    pages: list[dict[str, Any]] = []
    statuses: list[int] = []
    cursor: int | None = None
    for _ in range(int(policy["maximum_pages"])):
        suffix = "" if cursor is None else f"?before_rowid={cursor}"
        status, payload, duration_ms, transport_bytes = _json_get(
            f"{BACKEND}/api/conversations/{conversation_id}{suffix}"
        )
        statuses.append(status)
        if status != 200:
            raise RuntimeError(f"Lecture de conversation refusée: HTTP {status}.")
        if not pages:
            if duration_ms > int(policy["maximum_first_page_duration_ms"]):
                raise RuntimeError(f"Première page trop lente: {duration_ms} ms.")
            if transport_bytes > int(policy["maximum_first_page_transport_bytes"]):
                raise RuntimeError(f"Première page trop volumineuse: {transport_bytes} octets.")
        page = {
            "messages": payload.get("messages") or [],
            "page": payload.get("page") or {},
            "duration_ms": duration_ms,
            "transport_bytes": transport_bytes,
        }
        pages.append(page)
        if not page["page"].get("hasOlderRows"):
            break
        next_cursor = page["page"].get("nextBeforeRowid")
        if next_cursor is None:
            raise RuntimeError("Page suivante annoncée sans curseur.")
        cursor = int(next_cursor)
    return pages, statuses


def _first_detail_ref(pages: list[dict[str, Any]]) -> tuple[str, str]:
    for page in pages:
        for message in page["messages"]:
            for invocation in message.get("toolInvocations") or []:
                detail = invocation.get("detailRef") or {}
                if detail.get("messageId") and detail.get("toolCallId"):
                    return str(detail["messageId"]), str(detail["toolCallId"])
    raise RuntimeError("Aucun reçu détaillé n'est disponible dans la conversation cible.")


def _run_chat_smoke(evidence_path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="marvin-td015-smoke-") as temporary:
        report_path = Path(temporary) / "chat-smoke.json"
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["MARVIN_SMOKE_REPORT_PATH"] = str(report_path)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_test_chat.py")],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        if not report_path.exists():
            raise RuntimeError("Le smoke chat n'a pas publié son rapport structuré.")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["returncode"] = completed.returncode
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_evidence = evidence_path.with_suffix(evidence_path.suffix + ".tmp")
        temporary_evidence.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_evidence.replace(evidence_path)
        if completed.returncode != 0:
            raise RuntimeError("Le smoke chat 5/5 a échoué.")
        return report


def run_cycle(
    policy: dict[str, Any], database: Path, cycle: int, smoke_evidence_path: Path
) -> dict[str, Any]:
    target_id, stored_bytes = _select_target(
        database, int(policy["target_selector"]["minimum_stored_bytes"])
    )
    pages, statuses = _collect_pages(target_id, policy["conversation"])
    chain = validate_page_chain(pages, policy["conversation"])
    message_id, tool_call_id = _first_detail_ref(pages)
    detail_status, detail_raw, detail_ms = _get(
        f"{BACKEND}/api/conversations/{target_id}/messages/{message_id}/tool-results/{tool_call_id}"
    )
    statuses.append(detail_status)
    wrong_status, _, wrong_ms = _get(
        f"{BACKEND}/api/conversations/00000000-0000-0000-0000-000000000000/messages/"
        f"{message_id}/tool-results/{tool_call_id}"
    )
    if detail_status != int(policy["detail"]["same_conversation_http"]):
        raise RuntimeError(f"Détail attendu en 200, reçu {detail_status}.")
    if wrong_status != int(policy["detail"]["cross_conversation_http"]):
        raise RuntimeError(f"Liaison croisée attendue en 404, reçue {wrong_status}.")
    frontend_status, _, frontend_ms = _get(f"{FRONTEND}/api/status", timeout=20)
    statuses.append(frontend_status)
    if frontend_status != 200:
        raise RuntimeError(f"Frontend indisponible: HTTP {frontend_status}.")
    chat = _run_chat_smoke(smoke_evidence_path)
    if int(chat.get("sample_count", 0)) != int(policy["chat_smoke"]["required_conversations"]):
        raise RuntimeError("Le smoke chat n'a pas couvert cinq conversations.")
    if int(chat.get("server_error_count", -1)) != int(policy["chat_smoke"]["maximum_http_5xx"]):
        raise RuntimeError("Un HTTP 5xx a été observé pendant le smoke chat.")
    if int(chat.get("console_error_count", -1)) != int(policy["chat_smoke"]["maximum_console_errors"]):
        raise RuntimeError("Une erreur console a été observée pendant le smoke chat.")
    server_5xx_count = sum(1 for status in statuses if status >= 500) + int(
        chat.get("server_error_count", 0)
    )
    if server_5xx_count:
        raise RuntimeError(f"{server_5xx_count} réponse(s) 5xx observée(s).")
    return {
        "cycle": cycle,
        "target_id_sha256": hashlib.sha256(target_id.encode("utf-8")).hexdigest(),
        "target_stored_bytes": stored_bytes,
        "page_chain": chain,
        "first_page_duration_ms": pages[0]["duration_ms"],
        "first_page_transport_bytes": pages[0]["transport_bytes"],
        "details_available": sum(int(page["page"].get("detailsAvailable") or 0) for page in pages),
        "detail_http": detail_status,
        "detail_transport_bytes": len(detail_raw),
        "detail_duration_ms": detail_ms,
        "cross_conversation_http": wrong_status,
        "cross_conversation_duration_ms": wrong_ms,
        "frontend_http": frontend_status,
        "frontend_duration_ms": frontend_ms,
        "chat_smoke": chat,
        "server_5xx_count": server_5xx_count,
        "passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Vérification d'un cycle TD-015")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--cycle", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    report = run_cycle(
        policy,
        args.database,
        args.cycle,
        args.output.with_suffix(".smoke.json"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
