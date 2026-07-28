"""Marvin Forge : corpus et évaluation déterministe des traces agentiques."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR
from durable_evidence_store import DurableEvidenceStore


SCENARIOS_PATH = Path(DATA_DIR) / "forge_scenarios.json"
RUNS_PATH = Path(DATA_DIR) / "forge_runs.jsonl"
_LOCK = threading.RLock()
_RUNS_STORE = None
_RUNS_STORE_PATH = None

_DEFAULT_SCENARIOS = [
    {
        "id": "safe-no-tools",
        "name": "Instruction explicite sans outil",
        "category": "intent",
        "description": "Vérifie qu'une réponse simple n'appelle aucun outil.",
        "prompt": "Réponds uniquement par OK, sans utiliser d'outil.",
        "model": None,
        "cortex": {
            "effort": "instant",
            "evidence": "none",
            "review": "none",
            "autonomy": "advise",
            "privacy": "local",
            "output": "chat",
        },
        "expectations": {
            "require_done": True,
            "forbid_all_tools": True,
            "contains_all": ["OK"],
            "max_duration_ms": 180000,
        },
        "enabled": True,
        "source": "regression-v2.190",
    },
    {
        "id": "explicit-council-five",
        "name": "Council 5 explicite",
        "category": "council",
        "description": "Vérifie qu'une demande Council explicite appelle le vrai outil.",
        "prompt": "En mode Council 5, compare trois stratégies de sauvegarde pour une PME.",
        "model": None,
        "cortex": {"review": "council5", "autonomy": "advise"},
        "expectations": {
            "require_done": True,
            "required_tools": ["ai_model_council"],
            "max_tool_calls": 1,
            "max_duration_ms": 600000,
        },
        "enabled": False,
        "source": "regression-v2.211",
    },
    {
        "id": "web-primary-evidence",
        "name": "Recherche avec sources primaires",
        "category": "research",
        "description": "Vérifie la collecte de preuves et la provenance web.",
        "prompt": "Recherche la documentation officielle actuelle de Python sur venv et résume-la.",
        "model": None,
        "cortex": {"evidence": "primary", "review": "verify", "autonomy": "advise"},
        "expectations": {
            "require_done": True,
            "required_any_tools": ["web_search", "web_deep_research"],
            "required_event_types": ["cortex_provenance"],
            "max_duration_ms": 600000,
        },
        "enabled": False,
        "source": "forge-seed",
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runs_store() -> DurableEvidenceStore:
    global _RUNS_STORE, _RUNS_STORE_PATH
    resolved = str(RUNS_PATH.resolve())
    if _RUNS_STORE is None or _RUNS_STORE_PATH != resolved:
        _RUNS_STORE = DurableEvidenceStore(resolved, stream_name="marvin.forge.runs")
        _RUNS_STORE_PATH = resolved
    return _RUNS_STORE


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validate_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Un scénario Forge doit être un objet.")
    scenario_id = str(raw.get("id") or uuid.uuid4().hex[:12]).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}", scenario_id):
        raise ValueError("Identifiant Forge invalide.")
    name = str(raw.get("name") or "").strip()
    prompt = str(raw.get("prompt") or "").strip()
    if not name or len(name) > 120:
        raise ValueError("Le nom Forge est requis et limité à 120 caractères.")
    if not prompt or len(prompt) > 12000:
        raise ValueError("Le prompt Forge est requis et limité à 12000 caractères.")
    expectations = raw.get("expectations") or {}
    if not isinstance(expectations, dict):
        raise ValueError("Les attentes Forge doivent être un objet.")
    cortex = raw.get("cortex") or {}
    if not isinstance(cortex, dict):
        raise ValueError("Le contrat Cortex Forge doit être un objet.")
    return {
        "id": scenario_id,
        "name": name,
        "category": str(raw.get("category") or "general")[:60],
        "description": str(raw.get("description") or "")[:500],
        "prompt": prompt,
        "model": str(raw["model"]).strip() if raw.get("model") else None,
        "cortex": cortex,
        "expectations": expectations,
        "enabled": bool(raw.get("enabled", True)),
        "source": str(raw.get("source") or "manual")[:120],
        "updated_at": _utc_now(),
    }


def list_scenarios() -> list[dict[str, Any]]:
    with _LOCK:
        if not SCENARIOS_PATH.exists():
            seeded = [_validate_scenario(item) for item in _DEFAULT_SCENARIOS]
            _atomic_write_json(SCENARIOS_PATH, seeded)
            return seeded
        try:
            raw = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Corpus Forge illisible : {exc}") from exc
        if not isinstance(raw, list):
            raise RuntimeError("Le corpus Forge doit contenir une liste.")
        return [_validate_scenario(item) for item in raw]


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    return next((item for item in list_scenarios() if item["id"] == scenario_id), None)


def save_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    scenario = _validate_scenario(raw)
    with _LOCK:
        scenarios = list_scenarios()
        index = next((i for i, item in enumerate(scenarios) if item["id"] == scenario["id"]), None)
        if index is None:
            scenarios.append(scenario)
        else:
            scenarios[index] = scenario
        _atomic_write_json(SCENARIOS_PATH, scenarios)
    return scenario


def delete_scenario(scenario_id: str) -> bool:
    with _LOCK:
        scenarios = list_scenarios()
        filtered = [item for item in scenarios if item["id"] != scenario_id]
        if len(filtered) == len(scenarios):
            return False
        _atomic_write_json(SCENARIOS_PATH, filtered)
        return True


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("type") or "")


def _event_tool(event: dict[str, Any]) -> str:
    return str(event.get("toolName") or event.get("tool_name") or "")


def _event_text(event: dict[str, Any]) -> str:
    value = event.get("content", event.get("text", ""))
    return value if isinstance(value, str) else ""


def grade_trace(
    scenario: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    expectations = scenario.get("expectations") or {}
    event_types = [_event_type(event) for event in events]
    tool_names = [_event_tool(event) for event in events if _event_type(event) == "tool_start"]
    response = "".join(_event_text(event) for event in events if _event_type(event) == "text").strip()
    errors = [
        str(event.get("message") or event.get("error") or "erreur")
        for event in events
        if _event_type(event) == "error"
    ]
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if expectations.get("require_done", True):
        check("done", "done" in event_types, "Événement done reçu" if "done" in event_types else "Événement done absent")
    check("no_error", not errors, "Aucune erreur SSE" if not errors else "; ".join(errors[:3]))

    if expectations.get("forbid_all_tools"):
        check("forbid_all_tools", not tool_names, f"Outils appelés : {tool_names}" if tool_names else "Aucun outil appelé")

    forbidden = {str(name) for name in expectations.get("forbidden_tools", [])}
    if forbidden:
        violations = sorted(forbidden.intersection(tool_names))
        check("forbidden_tools", not violations, f"Interdits appelés : {violations}" if violations else "Aucun outil interdit")

    required = {str(name) for name in expectations.get("required_tools", [])}
    if required:
        missing = sorted(required.difference(tool_names))
        check("required_tools", not missing, f"Manquants : {missing}" if missing else "Tous les outils requis ont été appelés")

    required_any = {str(name) for name in expectations.get("required_any_tools", [])}
    if required_any:
        found = sorted(required_any.intersection(tool_names))
        check("required_any_tools", bool(found), f"Trouvés : {found}" if found else f"Aucun parmi : {sorted(required_any)}")

    if expectations.get("max_tool_calls") is not None:
        maximum = max(0, int(expectations["max_tool_calls"]))
        check("max_tool_calls", len(tool_names) <= maximum, f"{len(tool_names)} appel(s), maximum {maximum}")

    for needle in expectations.get("contains_all", []):
        expected = str(needle)
        check(f"contains:{expected}", expected.casefold() in response.casefold(), f"Texte requis : {expected}")

    for needle in expectations.get("contains_none", []):
        forbidden_text = str(needle)
        check(
            f"excludes:{forbidden_text}",
            forbidden_text.casefold() not in response.casefold(),
            f"Texte interdit : {forbidden_text}",
        )

    required_events = {str(name) for name in expectations.get("required_event_types", [])}
    if required_events:
        missing_events = sorted(required_events.difference(event_types))
        check("required_event_types", not missing_events, f"Événements manquants : {missing_events}" if missing_events else "Événements requis présents")

    if expectations.get("max_duration_ms") is not None and duration_ms is not None:
        maximum_duration = max(1, int(expectations["max_duration_ms"]))
        check("max_duration_ms", duration_ms <= maximum_duration, f"{duration_ms} ms, maximum {maximum_duration} ms")

    model_event = next((event for event in reversed(events) if _event_type(event) == "model_info"), {})
    model = str(model_event.get("model") or model_event.get("modelName") or "")
    if expectations.get("model_contains"):
        needle = str(expectations["model_contains"])
        check("model_contains", needle.casefold() in model.casefold(), f"Modèle observé : {model or 'inconnu'}")

    passed_count = sum(1 for item in checks if item["passed"])
    score = round(passed_count / len(checks), 4) if checks else 1.0
    return {
        "success": all(item["passed"] for item in checks),
        "score": score,
        "checks": checks,
        "tool_names": tool_names,
        "event_types": event_types,
        "response_preview": response[:500],
        "duration_ms": duration_ms,
        "model": model or None,
    }


def record_run(
    scenario_id: str,
    events: list[dict[str, Any]],
    *,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise ValueError("Scénario Forge introuvable.")
    grade = grade_trace(scenario, events, duration_ms=duration_ms)
    run = {
        "id": uuid.uuid4().hex,
        "scenario_id": scenario_id,
        "scenario_name": scenario["name"],
        "created_at": _utc_now(),
        **grade,
    }
    with _LOCK:
        return _runs_store().append(run)


def list_runs(*, limit: int = 200, scenario_id: str | None = None) -> list[dict[str, Any]]:
    bounded = max(1, min(int(limit), 2000))
    with _LOCK:
        return _runs_store().recent(
            bounded,
            predicate=(
                (lambda row: row.get("scenario_id") == scenario_id)
                if scenario_id
                else None
            ),
        )


def _window_metric(values: list[bool], k: int, *, require_all: bool) -> bool | None:
    if len(values) < k:
        return None
    window = values[:k]
    return all(window) if require_all else any(window)


def summary() -> dict[str, Any]:
    scenarios = list_scenarios()
    runs = list_runs(limit=2000)
    by_scenario: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_runs = [run for run in runs if run.get("scenario_id") == scenario["id"]]
        values = [bool(run.get("success")) for run in scenario_runs]
        by_scenario.append(
            {
                "id": scenario["id"],
                "name": scenario["name"],
                "category": scenario["category"],
                "enabled": scenario["enabled"],
                "runs": len(values),
                "success_rate": round(sum(values) / len(values), 4) if values else None,
                "pass_1": _window_metric(values, 1, require_all=True),
                "pass_3": _window_metric(values, 3, require_all=True),
                "pass_5": _window_metric(values, 5, require_all=True),
                "pass_at_3": _window_metric(values, 3, require_all=False),
                "last_run": scenario_runs[0] if scenario_runs else None,
            }
        )
    total_success = sum(1 for run in runs if run.get("success"))
    return {
        "scenarios": len(scenarios),
        "enabled_scenarios": sum(1 for item in scenarios if item["enabled"]),
        "runs": len(runs),
        "success_rate": round(total_success / len(runs), 4) if runs else None,
        "by_scenario": by_scenario,
        "integrity": _runs_store().verify(),
    }
