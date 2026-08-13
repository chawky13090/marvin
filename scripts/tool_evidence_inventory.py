"""Inventaire en lecture seule des preuves disponibles par outil et action Marvin.

Ce module ne modifie ni le catalogue, ni le routage, ni la base. Il sépare les
références de tests, les exécutions techniques et les demandes humaines persistées.
Une exécution SQLite réussie ne vaut jamais, à elle seule, oracle métier E7.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools  # noqa: E402
from config import (  # noqa: E402
    CONDITIONAL_TOOL_SAFE_ACTIONS,
    CONDITIONAL_TOOL_STANDARD_ACTIONS,
    DANGEROUS_TOOLS,
    SECURE_BLOCKED_TOOLS,
)

from audit_tool_coverage import build_report as build_static_coverage  # noqa: E402


DEFAULT_ACTION = "__default__"
EVIDENCE_LEVELS = {
    "E0": "présent dans le catalogue",
    "E1": "schéma et exécuteur présents dans le harnais",
    "E2": "référence de test automatisé identifiée",
    "E3": "intégration isolée explicitement prouvée",
    "E4": "exécution E2E avec oracle d'état indépendant",
    "E5": "automatisme réel attribué et réussi",
    "E6": "demande humaine persistée liée à une exécution réussie",
    "E7": "résultat métier et rollback explicitement vérifiés",
}


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _action_values(specification: dict[str, Any]) -> tuple[str, ...]:
    parameters = specification.get("function", {}).get("parameters", {})
    action = parameters.get("properties", {}).get("action", {})
    values = action.get("enum") if isinstance(action, dict) else None
    if isinstance(values, list):
        cleaned = tuple(
            dict.fromkeys(str(value).strip() for value in values if str(value).strip())
        )
        if cleaned:
            return cleaned
    return (DEFAULT_ACTION,)


def _risk(tool_name: str, action: str) -> tuple[int, str]:
    if tool_name in CONDITIONAL_TOOL_SAFE_ACTIONS:
        if action in CONDITIONAL_TOOL_SAFE_ACTIONS[tool_name]:
            return 1, "conditional_safe_action"
        if action in CONDITIONAL_TOOL_STANDARD_ACTIONS.get(tool_name, frozenset()):
            return 2, "conditional_reversible_action"
        return 4, "conditional_sensitive_action"
    if tool_name in DANGEROUS_TOOLS:
        destructive = any(
            token in f"{tool_name}.{action}".casefold()
            for token in ("delete", "remove", "uninstall", "kill", "debloat")
        )
        return (5 if destructive else 4), (
            "dangerous_destructive_tool" if destructive else "dangerous_tool"
        )
    if tool_name in SECURE_BLOCKED_TOOLS:
        return 3, "secure_profile_blocked"
    return 1, "catalog_default_read_or_low_impact_unverified"


def _open_readonly(database_path: Path) -> sqlite3.Connection:
    uri = database_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _parse_args(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _execution_rows(database_path: Path) -> Iterable[sqlite3.Row]:
    with _open_readonly(database_path) as connection:
        required = {"conversations", "messages", "tool_executions"}
        existing = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not required <= existing:
            missing = ", ".join(sorted(required - existing))
            raise RuntimeError(f"Tables de preuve absentes : {missing}")
        yield from connection.execute(
            """
            SELECT e.id, e.tool_name, e.args, e.success, e.duration_ms,
                   e.created_at, e.conversation_id, e.request_id,
                   c.id AS persisted_conversation_id,
                   (
                     SELECT m.id FROM messages AS m
                     WHERE m.conversation_id = e.conversation_id
                       AND m.role = 'user'
                       AND m.created_at <= e.created_at
                     ORDER BY m.created_at DESC, m.rowid DESC
                     LIMIT 1
                   ) AS user_message_id
            FROM tool_executions AS e
            LEFT JOIN conversations AS c ON c.id = e.conversation_id
            ORDER BY e.created_at ASC, e.id ASC
            """
        )


def _usage(database_path: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, int]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "persisted_conversations": set(),
            "human_messages": set(),
            "successful_human_messages": set(),
            "orphan_or_ephemeral_executions": 0,
            "last_execution_at": None,
        }
    )
    totals = Counter()
    for row in _execution_rows(database_path):
        args = _parse_args(row["args"])
        action = str(args.get("action") or DEFAULT_ACTION).strip() or DEFAULT_ACTION
        key = (str(row["tool_name"]), action)
        bucket = buckets[key]
        bucket["executions"] += 1
        succeeded = bool(row["success"])
        bucket["successful_executions" if succeeded else "failed_executions"] += 1
        bucket["last_execution_at"] = row["created_at"]
        totals["executions"] += 1
        if row["persisted_conversation_id"]:
            bucket["persisted_conversations"].add(row["persisted_conversation_id"])
            totals["persisted_context_executions"] += 1
        else:
            bucket["orphan_or_ephemeral_executions"] += 1
            totals["orphan_or_ephemeral_executions"] += 1
        if row["user_message_id"]:
            bucket["human_messages"].add(row["user_message_id"])
            if succeeded:
                bucket["successful_human_messages"].add(row["user_message_id"])
    normalized: dict[tuple[str, str], dict[str, Any]] = {}
    for key, bucket in buckets.items():
        normalized[key] = {
            **{
                name: value
                for name, value in bucket.items()
                if not isinstance(value, set)
            },
            "persisted_conversation_count": len(bucket["persisted_conversations"]),
            "distinct_human_message_count": len(bucket["human_messages"]),
            "successful_human_message_count": len(
                bucket["successful_human_messages"]
            ),
        }
    totals["distinct_tool_action_pairs_executed"] = len(normalized)
    return normalized, dict(totals)


def _flags(
    *, harness: bool, automated_test: bool, usage: dict[str, Any], e7_verified: bool
) -> dict[str, bool | None]:
    return {
        "E0": True,
        "E1": harness,
        "E2": automated_test,
        # None signifie non évaluable depuis les sources de cette version. Il ne
        # doit jamais être interprété comme une preuve d'absence.
        "E3": None,
        "E4": None,
        "E5": None,
        "E6": usage.get("successful_human_message_count", 0) > 0,
        "E7": True if e7_verified else None,
    }


def build_inventory(
    database_path: Path,
    *,
    explicit_e7: dict[tuple[str, str], dict[str, Any]] | None = None,
    schema_version: str = "1.1",
) -> dict[str, Any]:
    explicit_e7 = explicit_e7 or {}
    static_report = build_static_coverage()
    static_by_name = {row["name"]: row for row in static_report["tools"]}
    usage_by_pair, usage_totals = _usage(database_path)
    rows: list[dict[str, Any]] = []
    known_pairs: set[tuple[str, str]] = set()
    specifications = {
        str(item.get("function", {}).get("name")): item
        for item in tools.TOOLS_SPEC
        if item.get("function", {}).get("name")
    }
    for tool_name in sorted(specifications):
        static = static_by_name.get(tool_name, {})
        for action in _action_values(specifications[tool_name]):
            pair = (tool_name, action)
            known_pairs.add(pair)
            usage = usage_by_pair.get(pair, {})
            evidence = _flags(
                harness=bool(static.get("harness")),
                automated_test=bool(static.get("automated_test")),
                usage=usage,
                e7_verified=pair in explicit_e7,
            )
            risk_tier, risk_basis = _risk(tool_name, action)
            missing = [level for level, present in evidence.items() if present is not True]
            priority = risk_tier * (1 + int(evidence["E4"] is not True)) * (
                1 + int(evidence["E7"] is not True)
            )
            rows.append(
                {
                    "tool": tool_name,
                    "action": action,
                    "catalog_key": f"{tool_name}:{action}",
                    "llm_visible": True,
                    "risk_tier": risk_tier,
                    "risk_basis": risk_basis,
                    "restricted": bool(static.get("restricted")),
                    "dangerous": bool(static.get("dangerous")),
                    "conditional": bool(static.get("conditional")),
                    "test_files": list(static.get("test_files") or ()),
                    "evidence": evidence,
                    "missing_evidence": missing,
                    "usage": usage,
                    "verification_priority": priority,
                    "rollback_verified": evidence["E7"] is True,
                    "explicit_evidence": {
                        "E7": explicit_e7[pair]
                    } if pair in explicit_e7 else {},
                }
            )
    unknown_pairs = sorted(set(usage_by_pair) - known_pairs)
    by_level = {
        level: sum(row["evidence"][level] is True for row in rows)
        for level in EVIDENCE_LEVELS
    }
    assessment_by_level = {
        level: {
            "verified": sum(row["evidence"][level] is True for row in rows),
            "absent": sum(row["evidence"][level] is False for row in rows),
            "unassessed": sum(row["evidence"][level] is None for row in rows),
        }
        for level in EVIDENCE_LEVELS
    }
    never_executed = sum(not row["usage"].get("executions") for row in rows)
    human_unused = sum(
        not row["usage"].get("distinct_human_message_count") for row in rows
    )
    return {
        "schema_version": schema_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": {
            "path": database_path.name,
            "sha256": _sha256(database_path),
            "mode": "read_only",
        },
        "methodology": {
            "levels": EVIDENCE_LEVELS,
            "human_unit": "distinct_persisted_user_message",
            "benchmark_ephemeral_exclusion": (
                "An execution is not human-linked unless its conversation and a preceding "
                "user message still exist in the authoritative SQLite database."
            ),
            "limitations": [
                "Historical executions do not identify automation versus Forge when their conversation was deleted.",
                "success=1 proves executor completion, not the requested business outcome.",
                "E3, E4, E5 and E7 are unassessed until an explicit evidence artifact evaluates them.",
                "Risk tier is a conservative inventory heuristic, not an authorization decision.",
            ],
        },
        "summary": {
            "catalog_tools": len(specifications),
            "tool_action_pairs": len(rows),
            "evidence_by_level": by_level,
            "evidence_assessment_by_level": assessment_by_level,
            "never_executed_pairs": never_executed,
            "without_human_linked_execution_pairs": human_unused,
            "usage_totals": usage_totals,
            "unknown_historical_tool_action_pairs": len(unknown_pairs),
        },
        "unknown_historical_pairs": [
            {
                "tool": tool,
                "action": action,
                "reason": (
                    "historical_execution_without_action"
                    if tool in specifications and action == DEFAULT_ACTION
                    else "historical_action_outside_current_schema"
                    if tool in specifications
                    else "tool_absent_from_current_catalog"
                ),
            }
            for tool, action in unknown_pairs
        ],
        "items": rows,
    }
