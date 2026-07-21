"""Evolution Lab : expériences bornées, promotion mesurée et rollback."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import database as db
from config import DATA_DIR


PATH = Path(DATA_DIR) / "evolution_experiments.json"
_LOCK = threading.RLock()
ALLOWED_TARGETS = {
    "council_concurrency": (1, 5),
    "cortex_search_concurrency": (1, 5),
    "research_swarm_concurrency": (1, 5),
    "web_depth": (1, 8),
    "rag_k": (2, 20),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict[str, Any]]:
    try:
        value = json.loads(PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _write(rows) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PATH)


def list_experiments(limit=100):
    rows = _load()
    rows.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return rows[:limit]


def get_experiment(experiment_id):
    return next((row for row in list_experiments(1000) if row["id"] == experiment_id), None)


def create(name: str, target: str, candidate_value: int, hypothesis: str) -> dict[str, Any]:
    if target not in ALLOWED_TARGETS:
        raise ValueError("Cible Evolution Lab non autorisée.")
    low, high = ALLOWED_TARGETS[target]
    candidate_value = int(candidate_value)
    if not low <= candidate_value <= high:
        raise ValueError(f"Valeur candidate hors limites {low}-{high}.")
    baseline = db.get_setting(target)
    row = {
        "id": "evo-" + uuid.uuid4().hex[:12], "name": name[:120], "target": target,
        "hypothesis": hypothesis[:1000], "baseline_value": baseline,
        "candidate_value": candidate_value, "status": "draft", "evaluation": None,
        "created_at": _now(), "updated_at": _now(),
    }
    with _LOCK:
        rows = _load(); rows.append(row); _write(rows)
    return row


def evaluate(experiment_id: str, baseline_trials: list[dict], candidate_trials: list[dict]) -> dict[str, Any]:
    if len(baseline_trials) < 3 or len(candidate_trials) < 3:
        raise ValueError("Trois essais baseline et trois essais candidate sont requis.")
    def metrics(rows):
        return {
            "trials": len(rows),
            "success_rate": sum(bool(row.get("success")) for row in rows) / len(rows),
            "average_duration_ms": mean(max(0, int(row.get("duration_ms") or 0)) for row in rows),
            "critical_failures": sum(bool(row.get("critical_failure")) for row in rows),
        }
    baseline, candidate = metrics(baseline_trials), metrics(candidate_trials)
    promotable = (
        candidate["critical_failures"] == 0
        and candidate["success_rate"] > baseline["success_rate"]
        and candidate["average_duration_ms"] <= max(1, baseline["average_duration_ms"]) * 1.25
    )
    evaluation = {"baseline": baseline, "candidate": candidate, "promotable": promotable, "evaluated_at": _now()}
    return _mutate(experiment_id, status="evaluated", evaluation=evaluation)


def _mutate(experiment_id: str, **updates):
    with _LOCK:
        rows = _load()
        for index, row in enumerate(rows):
            if row["id"] == experiment_id:
                row = {**row, **updates, "updated_at": _now()}
                rows[index] = row; _write(rows); return row
    return None


def promote(experiment_id: str, confirmed: bool) -> dict[str, Any]:
    row = get_experiment(experiment_id)
    if not row:
        raise ValueError("Expérience introuvable.")
    if not confirmed or not (row.get("evaluation") or {}).get("promotable"):
        raise ValueError("Promotion refusée : confirmation et seuils de qualité requis.")
    previous = db.get_setting(row["target"])
    db.set_setting(row["target"], row["candidate_value"])
    return _mutate(experiment_id, status="promoted", promoted_at=_now(), rollback_value=previous)


def rollback(experiment_id: str, confirmed: bool) -> dict[str, Any]:
    row = get_experiment(experiment_id)
    if not row or row.get("status") != "promoted" or not confirmed:
        raise ValueError("Rollback refusé.")
    db.set_setting(row["target"], row.get("rollback_value"))
    return _mutate(experiment_id, status="rolled_back", rolled_back_at=_now())

