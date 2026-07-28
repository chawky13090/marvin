"""Model Market : catalogue et classement déterministe des modèles Ollama Cloud."""
from __future__ import annotations

import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cloud_routing
import bug_log
from config import DATA_DIR, OLLAMA_URL
from durable_evidence_store import DurableEvidenceStore


OBSERVATIONS_PATH = Path(DATA_DIR) / "model_market_observations.jsonl"
_NEEDS = {
    "general",
    "reasoning",
    "agentic",
    "code",
    "code_architecture",
    "code_implementation",
    "code_review",
    "vision",
    "research",
    "verification",
    "synthesis",
    "productivity",
    "multilingual",
}
_FAMILY_PREFERENCES = {
    "general": ("deepseek", "minimax", "glm", "qwen", "mistral", "nemotron", "kimi"),
    "reasoning": ("deepseek", "glm", "minimax", "qwen", "nemotron", "mistral", "kimi"),
    "agentic": ("minimax", "glm", "nemotron", "mistral", "deepseek", "qwen", "kimi"),
    "code": ("glm", "deepseek", "kimi", "minimax", "qwen", "mistral", "nemotron"),
    "code_architecture": ("glm", "deepseek", "minimax", "qwen", "mistral", "nemotron", "kimi"),
    "code_implementation": ("kimi", "glm", "deepseek", "minimax", "qwen", "mistral", "nemotron"),
    "code_review": ("glm", "mistral", "deepseek", "nemotron", "qwen", "minimax", "kimi"),
    "vision": ("minimax", "qwen", "gemma", "mistral", "kimi", "glm", "deepseek", "nemotron"),
    "research": ("deepseek", "minimax", "qwen", "glm", "mistral", "nemotron", "kimi"),
    "verification": ("mistral", "glm", "nemotron", "deepseek", "qwen", "minimax", "kimi"),
    "synthesis": ("deepseek", "minimax", "glm", "mistral", "qwen", "nemotron", "kimi"),
    "productivity": ("minimax", "mistral", "qwen", "glm", "deepseek", "nemotron", "kimi"),
    "multilingual": ("qwen", "mistral", "minimax", "glm", "deepseek", "nemotron", "kimi"),
}
_NEED_LABELS = {
    "general": "conversation générale",
    "reasoning": "raisonnement complexe",
    "agentic": "orchestration agentique",
    "code": "ingénierie logicielle",
    "code_architecture": "architecture logicielle",
    "code_implementation": "implémentation de code",
    "code_review": "revue et validation de code",
    "vision": "vision et multimodal",
    "research": "recherche et navigation",
    "verification": "vérification critique",
    "synthesis": "synthèse finale",
    "productivity": "documents et productivité",
    "multilingual": "français et multilingue",
}
RECOMMENDED_CLOUD_MODELS = (
    {"model": "deepseek-v4-pro:cloud", "roles": ("general", "reasoning", "research", "synthesis"),
     "reason": "raisonnement profond, navigation et contexte long"},
    {"model": "glm-5.2:cloud", "roles": ("code_architecture", "code_review", "agentic"),
     "reason": "ingénierie de projet et tâches longues"},
    {"model": "kimi-k2.7-code:cloud", "roles": ("code_implementation",),
     "reason": "implémentation logicielle agentique spécialisée"},
    {"model": "minimax-m3:cloud", "roles": ("agentic", "vision", "research"),
     "reason": "orchestration, navigation, multimodal et contexte long"},
    {"model": "qwen3.5:397b-cloud", "roles": ("vision", "multilingual"),
     "reason": "vision unifiée et couverture multilingue"},
    {"model": "mistral-large-3:675b-cloud", "roles": ("verification", "productivity", "multilingual"),
     "reason": "vérification structurée, français, JSON et entreprise"},
    {"model": "nemotron-3-super:cloud", "roles": ("agentic", "verification"),
     "reason": "collaboration multi-agent et automatisation IT"},
    {"model": "minimax-m2.7:cloud", "roles": ("productivity", "code_review"),
     "reason": "documents professionnels et revue d'ingénierie"},
)
DISCOVERABLE_CLOUD_MODELS = tuple(dict.fromkeys([
    *(item["model"] for item in RECOMMENDED_CLOUD_MODELS),
    "nemotron-3-ultra:cloud",
    "deepseek-v4-flash:cloud",
    "kimi-k2.6:cloud",
    "gpt-oss:120b-cloud",
    "devstral-small-2:24b-cloud",
]))
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}(?::[A-Za-z0-9._-]{1,80})?$")
_SYNC_LOCK = threading.RLock()
_SYNC_STATE: dict[str, Any] = {
    "running": False, "started_at": None, "finished_at": None,
    "results": [], "error": None,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _observation_store() -> DurableEvidenceStore:
    return DurableEvidenceStore(
        OBSERVATIONS_PATH,
        stream_name="marvin.model_market.observations",
    )


def evidence_integrity() -> dict[str, Any]:
    return _observation_store().verify()


def _need(value: str) -> str:
    value = str(value or "general").strip().lower()
    return value if value in _NEEDS else "general"


def record_observation(
    model: str,
    need: str,
    success: bool,
    duration_ms: int,
    *,
    phase: str = "",
    error_type: str | None = None,
) -> dict[str, Any] | None:
    """Enregistre uniquement la télémétrie technique d'un appel réel, jamais son contenu."""
    if not model or not cloud_routing.is_cloud_model(model):
        return None
    normalized_model = str(model).strip()
    if not _MODEL_NAME_RE.fullmatch(normalized_model):
        return None
    try:
        normalized_duration = max(0, min(int(duration_ms or 0), 3_600_000))
    except (TypeError, ValueError, OverflowError):
        normalized_duration = 0
    row = {
        "at": _utc_now(),
        "model": normalized_model,
        "family": cloud_routing.model_family(normalized_model),
        "need": _need(need),
        "success": bool(success),
        "duration_ms": normalized_duration,
        "phase": re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(phase or ""))[:80],
        "error_type": re.sub(
            r"[^A-Za-z0-9_.:-]+",
            "_",
            str(error_type or ""),
        )[:80] or None,
    }
    try:
        return _observation_store().append(row)
    except Exception as exc:
        bug_log.log_bug(
            "model_market_observation",
            "Persistance d'une observation de modèle impossible.",
            context={"error_type": type(exc).__name__},
        )
        return None


def list_observations(limit: int = 500) -> list[dict[str, Any]]:
    return _observation_store().recent(max(1, min(int(limit), 5000)))


def _stats() -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in list_observations(5000):
        model = str(row.get("model"))
        need = _need(str(row.get("need")))
        grouped[(model, need)].append(row)
        phase = str(row.get("phase") or "").lower()
        derived_need = None
        if need == "code":
            if phase == "architecture":
                derived_need = "code_architecture"
            elif "implementation" in phase or "repair" in phase:
                derived_need = "code_implementation"
            elif any(marker in phase for marker in ("review", "gate", "validation", "test_", "adjudication")):
                derived_need = "code_review"
        if derived_need:
            grouped[(model, derived_need)].append(row)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in grouped.items():
        rows = rows[:100]
        successes = [row for row in rows if row.get("success")]
        durations = [int(row.get("duration_ms") or 0) for row in successes if row.get("duration_ms")]
        result[key] = {
            "calls": len(rows),
            "successes": len(successes),
            "success_rate": round(len(successes) / len(rows), 4),
            "average_duration_ms": round(sum(durations) / len(durations)) if durations else None,
            "last_seen": rows[0].get("at"),
        }
    return result


def _official_prior(model: str, need: str) -> tuple[float, str | None]:
    """Small documented cold-start prior; real observations remain decisive."""
    low = model.lower()
    adjustments: list[tuple[bool, float, str]] = [
        (
            low.startswith("deepseek") and need in {"general", "reasoning", "research", "synthesis"},
            7.0,
            "prior officiel : raisonnement, recherche et contexte long",
        ),
        (
            low.startswith("glm") and need in {"code", "code_architecture", "code_review", "agentic"},
            7.0,
            "prior officiel : ingénierie de projet et tâches longues",
        ),
        (
            low.startswith("kimi") and need == "code_implementation" and "code" in low,
            9.0,
            "prior officiel : modèle spécialisé en implémentation agentique",
        ),
        (
            "minimax-m3" in low and need in {"general", "reasoning", "agentic", "vision", "research"},
            9.0,
            "prior officiel : agentique, navigation, multimodal et contexte long",
        ),
        (
            "minimax-m2.7" in low and need in {"productivity", "code_review"},
            8.0,
            "prior officiel : productivité professionnelle et ingénierie",
        ),
        (
            low.startswith("qwen") and need in {"vision", "multilingual"},
            9.0,
            "prior officiel : vision unifiée et couverture multilingue",
        ),
        (
            low.startswith("gemma4") and need == "vision",
            8.0,
            "prior officiel : modèle multimodal Cloud natif",
        ),
        (
            low.startswith("mistral") and need in {"verification", "multilingual", "productivity"},
            7.0,
            "prior officiel : JSON, function calling, multilingue et entreprise",
        ),
        (
            low.startswith("nemotron") and need in {"agentic", "verification"},
            7.0,
            "prior officiel : collaboration multi-agent et automatisation IT",
        ),
    ]
    score = 0.0
    reasons = []
    for applies, value, reason in adjustments:
        if applies:
            score += value
            reasons.append(reason)
    return score, "; ".join(reasons) if reasons else None


def _score(model: str, need: str, stats: dict[str, Any] | None) -> tuple[float, list[str]]:
    family = cloud_routing.model_family(model)
    preferences = _FAMILY_PREFERENCES[_need(need)]
    reasons: list[str] = []
    try:
        rank = preferences.index(family)
        score = 55.0 - rank * 4.0
        reasons.append(f"famille classée {rank + 1} pour {need}")
    except ValueError:
        score = 30.0
        reasons.append("famille disponible hors classement spécialisé")
    prior_score, prior_reason = _official_prior(model, _need(need))
    score += prior_score
    if prior_reason:
        reasons.append(prior_reason)
    learned = cloud_routing.get_model_capabilities().get(model, {}).get(need, {}).get("ok")
    if learned is True:
        score += 15
        reasons.append("capacité prouvée par un appel réel")
    elif learned is False:
        score -= 40
        reasons.append("incapacité observée")
    if stats:
        score += (float(stats["success_rate"]) - 0.5) * 30
        reasons.append(f"{stats['success_rate'] * 100:.0f}% de succès observé")
        latency = stats.get("average_duration_ms")
        if latency:
            score += max(-10.0, min(8.0, (45_000 - latency) / 5_000))
            reasons.append(f"latence moyenne {latency} ms")
    else:
        reasons.append("aucune télémétrie payante déclenchée artificiellement")
    return round(max(0.0, min(100.0, score)), 2), reasons


def catalog(need: str = "general") -> dict[str, Any]:
    need = _need(need)
    integrity = evidence_integrity()
    observations = _stats() if integrity["valid"] else {}
    models = []
    for model in cloud_routing.list_installed_cloud_models():
        model_stats = observations.get((model, need))
        score, reasons = _score(model, need, model_stats)
        models.append({
            "model": model,
            "family": cloud_routing.model_family(model),
            "need": need,
            "score": score,
            "observations": model_stats or {
                "calls": 0, "successes": 0, "success_rate": None,
                "average_duration_ms": None, "last_seen": None,
            },
            "reasons": reasons,
        })
    models.sort(key=lambda item: (-item["score"], item["model"]))
    return {
        "need": need,
        "need_label": _NEED_LABELS[need],
        "models": models,
        "installed_count": len(models),
        "observation_count": len(list_observations(5000)) if integrity["valid"] else 0,
        "policy": "passive_real_calls_only",
        "observation_window_per_model_need": 100,
        "telemetry_trusted": integrity["valid"],
        "evidence_integrity": integrity,
        "fallback_reason": None if integrity["valid"] else "observation_integrity_invalid",
        "generated_at": _utc_now(),
    }


def recommend(
    need: str = "general",
    *,
    count: int = 1,
    distinct_families: bool = False,
    exclude_models: set[str] | frozenset[str] = frozenset(),
    exclude_families: set[str] | frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    candidates = catalog(need)["models"]
    selected: list[dict[str, Any]] = []
    families: set[str] = set()
    for item in candidates:
        if item["model"] in exclude_models or item["family"] in exclude_families:
            continue
        if distinct_families and item["family"] in families:
            continue
        selected.append(item)
        families.add(item["family"])
        if len(selected) >= max(1, min(int(count), 10)):
            break
    return selected


def _auto_sync_enabled() -> bool:
    try:
        value = __import__("database").get_setting("cloud_auto_sync")
    except Exception:
        value = None
    return value is not False


def fleet_status() -> dict[str, Any]:
    installed = cloud_routing.list_installed_cloud_models()
    installed_set = set(installed)
    recommended = [
        {**item, "installed": item["model"] in installed_set}
        for item in RECOMMENDED_CLOUD_MODELS
    ]
    return {
        "installed": installed,
        "installed_count": len(installed),
        "recommended": recommended,
        "missing_recommended": [item["model"] for item in recommended if not item["installed"]],
        "discoverable": [
            {"model": model, "installed": model in installed_set}
            for model in DISCOVERABLE_CLOUD_MODELS
        ],
        "arbitrary_cloud_pull_supported": True,
        "auto_sync_enabled": _auto_sync_enabled(),
        "sync": dict(_SYNC_STATE),
    }


def _validate_cloud_model_name(model: str) -> str:
    normalized = str(model or "").strip()
    if not _MODEL_NAME_RE.fullmatch(normalized):
        raise ValueError("Nom de modèle Ollama invalide.")
    if normalized not in DISCOVERABLE_CLOUD_MODELS and not cloud_routing.is_cloud_model(normalized):
        raise ValueError("Seuls les modèles Ollama Cloud sont acceptés.")
    return normalized


async def pull_cloud_model(model: str, *, timeout_seconds: int = 300) -> dict[str, Any]:
    import httpx

    normalized = _validate_cloud_model_name(model)
    if normalized in cloud_routing.list_installed_cloud_models():
        return {"model": normalized, "success": True, "status": "already_installed"}
    started = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(max(30, min(int(timeout_seconds), 900)), connect=10.0)
        ) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/pull",
                json={"model": normalized, "stream": False, "insecure": False},
            )
            response.raise_for_status()
            payload = response.json()
        success = str(payload.get("status") or "").lower() == "success"
        return {
            "model": normalized,
            "success": success,
            "status": str(payload.get("status") or "unknown")[:300],
            "duration_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        }
    except Exception as exc:
        return {
            "model": normalized,
            "success": False,
            "status": "failed",
            "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            "duration_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        }


async def sync_recommended_cloud_models() -> dict[str, Any]:
    enabled, _ = cloud_routing.get_cloud_config()
    if not enabled:
        return {"success": False, "skipped": True, "reason": "cloud_disabled"}
    if not _auto_sync_enabled():
        return {"success": False, "skipped": True, "reason": "auto_sync_disabled"}
    with _SYNC_LOCK:
        if _SYNC_STATE["running"]:
            return {"success": False, "skipped": True, "reason": "already_running"}
        _SYNC_STATE.update({
            "running": True, "started_at": _utc_now(), "finished_at": None,
            "results": [], "error": None,
        })
    try:
        installed = set(cloud_routing.list_installed_cloud_models())
        results = []
        for item in RECOMMENDED_CLOUD_MODELS:
            if item["model"] in installed:
                continue
            result = await pull_cloud_model(item["model"])
            results.append(result)
            if result.get("success"):
                installed.add(item["model"])
        with _SYNC_LOCK:
            _SYNC_STATE["results"] = results
            _SYNC_STATE["running"] = False
            _SYNC_STATE["finished_at"] = _utc_now()
        return {
            "success": all(item.get("success") for item in results),
            "pulled": [item["model"] for item in results if item.get("success")],
            "failed": [item for item in results if not item.get("success")],
            "fleet": fleet_status(),
        }
    except Exception as exc:
        with _SYNC_LOCK:
            _SYNC_STATE["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        return {"success": False, "error": _SYNC_STATE["error"]}
    finally:
        with _SYNC_LOCK:
            _SYNC_STATE["running"] = False
            _SYNC_STATE["finished_at"] = _utc_now()
