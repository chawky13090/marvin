"""Analyse locale et agrégée des parcours outillés réellement persistés."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA = "marvin.real-usage-journeys/1.0"
REQUIRED_FUTURE_METADATA = (
    "app_version",
    "model_name",
    "runtime_mode",
    "profile_name",
    "selector_version",
    "candidate_count",
    "candidate_set_sha256",
    "tool_call_id",
)


def _parse_timestamp(value: str) -> datetime:
    normalized = str(value).strip().replace(" ", "T")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
    temporary.replace(path)


def _load_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema") != "marvin.real-usage-journeys-policy/1.0":
        raise ValueError("Politique de parcours réel incompatible.")
    _parse_timestamp(policy["future_validation_start_utc"])
    return policy


def _fetch_requests(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT m.id AS message_id, m.conversation_id, m.created_at AS request_at,
               m.client_request_id AS request_id, e.id AS execution_id,
               e.tool_name, e.success, e.created_at AS execution_at,
               e.tool_call_id, e.app_version, e.model_name, e.runtime_mode,
               e.profile_name, e.selector_version, e.candidate_count,
               e.candidate_set_sha256, e.execution_source
        FROM messages AS m
        INNER JOIN conversations AS c ON c.id = m.conversation_id
        LEFT JOIN tool_executions AS e
          ON e.request_id = m.client_request_id
         AND (e.conversation_id = m.conversation_id OR e.conversation_id IS NULL)
        WHERE m.role = 'user' AND m.client_request_id IS NOT NULL
        ORDER BY m.created_at, m.rowid, e.created_at, e.id
        """
    ).fetchall()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        request_id = str(row["request_id"])
        conversation_id = str(row["conversation_id"])
        request = grouped.setdefault(
            (conversation_id, request_id),
            {
                "message_id": str(row["message_id"]),
                "conversation_id": conversation_id,
                "request_at": str(row["request_at"]),
                "executions": [],
            },
        )
        if row["execution_id"] is not None:
            request["executions"].append(
                {key: row[key] for key in (
                    "execution_id", "tool_name", "success", "execution_at",
                    "tool_call_id", "app_version", "model_name", "runtime_mode",
                    "profile_name", "selector_version", "candidate_count",
                    "candidate_set_sha256", "execution_source",
                )}
            )
    return list(grouped.values())


def _conversation_activity(connection: sqlite3.Connection) -> dict[str, Any]:
    connection.row_factory = sqlite3.Row
    last_users = {
        str(row["conversation_id"]): str(row["last_user_at"])
        for row in connection.execute(
            """SELECT conversation_id, MAX(created_at) AS last_user_at
               FROM messages WHERE role = 'user' GROUP BY conversation_id"""
        )
    }
    starts = sorted(
        (str(row["id"]), _parse_timestamp(row["created_at"]))
        for row in connection.execute("SELECT id, created_at FROM conversations")
    )
    return {"last_users": last_users, "starts": starts}


def _probable_abandonment(
    request: dict[str, Any], activity: dict[str, Any], window_minutes: int
) -> bool:
    executions = request["executions"]
    if not executions or bool(executions[-1]["success"]):
        return False
    last_user = activity["last_users"].get(request["conversation_id"])
    if last_user != request["request_at"]:
        return False
    start = _parse_timestamp(request["request_at"])
    deadline = start + timedelta(minutes=window_minutes)
    return any(
        conversation_id != request["conversation_id"] and start < created <= deadline
        for conversation_id, created in activity["starts"]
    )


def _request_status(executions: list[dict[str, Any]]) -> str:
    if not executions:
        return "no_tool_execution"
    outcomes = [bool(item["success"]) for item in executions]
    if all(outcomes):
        return "all_technical_receipts_successful"
    if not any(outcomes):
        return "all_technical_receipts_failed"
    return "mixed_technical_receipts"


def analyze(database_path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    uri = database_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        requests = _fetch_requests(connection)
        activity = _conversation_activity(connection)
    finally:
        connection.close()

    boundary = _parse_timestamp(policy["future_validation_start_utc"])
    window = int(policy["probable_abandonment_window_minutes"])
    split_counts: Counter[str] = Counter()
    status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    technical_recovery: Counter[str] = Counter()
    terminal_failure: Counter[str] = Counter()
    probable_abandonment: Counter[str] = Counter()
    exact_correlation: Counter[str] = Counter()
    metadata_complete: Counter[str] = Counter()
    version_counts: Counter[str] = Counter()
    execution_count: Counter[str] = Counter()

    for request in requests:
        request_at = _parse_timestamp(request["request_at"])
        executions = request["executions"]
        future = request_at >= boundary
        complete = bool(executions) and all(
            all(item.get(field) is not None for field in REQUIRED_FUTURE_METADATA)
            for item in executions
        )
        split = "future_validation_eligible" if future and complete else (
            "future_unassessed_incomplete_metadata" if future else "historical_development"
        )
        split_counts[split] += 1
        status_counts[split][_request_status(executions)] += 1
        execution_count[split] += len(executions)
        if executions and all(item.get("tool_call_id") for item in executions):
            exact_correlation[split] += 1
        if complete:
            metadata_complete[split] += 1
        outcomes = [bool(item["success"]) for item in executions]
        if any(not value for value in outcomes) and any(
            value and any(not previous for previous in outcomes[:index])
            for index, value in enumerate(outcomes)
        ):
            technical_recovery[split] += 1
        if outcomes and not outcomes[-1]:
            terminal_failure[split] += 1
        if _probable_abandonment(request, activity, window):
            probable_abandonment[split] += 1
        if split == "future_validation_eligible":
            versions = sorted({str(item["app_version"]) for item in executions})
            version_counts[versions[0] if len(versions) == 1 else "mixed_versions"] += 1

    splits = {}
    for split in (
        "historical_development", "future_validation_eligible",
        "future_unassessed_incomplete_metadata",
    ):
        splits[split] = {
            "request_count": split_counts[split],
            "execution_count": execution_count[split],
            "request_status": dict(sorted(status_counts[split].items())),
            "technical_recovery_request_count": technical_recovery[split],
            "terminal_technical_failure_request_count": terminal_failure[split],
            "probable_abandonment_signal_count": probable_abandonment[split],
            "exact_tool_call_correlation_request_count": exact_correlation[split],
            "complete_execution_metadata_request_count": metadata_complete[split],
        }
    result = {
        "schema": SCHEMA,
        "policy_sha256": _sha256(policy),
        "future_validation_start_utc": policy["future_validation_start_utc"],
        "source": {
            "unit": "persisted_user_message_with_client_request_id",
            "ephemeral_or_orphan_execution_excluded": True,
            "plaintext_user_content_read": False,
            "identifiers_published": False,
        },
        "semantics": {
            "technical_receipt_success_is_not_business_success": True,
            "business_satisfaction": "UNASSESSED",
            "probable_abandonment_is_not_proof": True,
            "historical_split_must_not_score_current_marvin": True,
            "mixed_versions_must_not_be_pooled": True,
        },
        "splits": splits,
        "future_validation_requests_by_app_version": dict(sorted(version_counts.items())),
    }
    result["aggregate_sha256"] = _sha256(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    policy = _load_policy(args.policy)
    result = analyze(args.database, policy)
    _write_atomic(args.output, result)
    print(json.dumps({
        "output": str(args.output),
        "aggregate_sha256": result["aggregate_sha256"],
        "splits": {key: value["request_count"] for key, value in result["splits"].items()},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
