"""Preuves locales de fiabilite et de latence pour le routage Ollama.

La selection statique borne les modeles par le materiel. Cette couche optionnelle
ne remplace ce choix que lorsqu'un modele exact, sur la machine actuelle, a reussi
plusieurs cycles complets appel d'outil -> resultat -> reponse finale.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import ollama_context_policy
from config import DATA_DIR


SCHEMA = "marvin.local-model-qualification/1.0"
PROFILE_PATH = DATA_DIR / "install" / "local-model-qualification.json"
QUALIFIED_ROLES = ("agent",)


def machine_key(hardware: dict[str, Any]) -> str:
    fingerprint = {
        "vendor": str(hardware.get("vendor") or "unknown"),
        "gpu": str(hardware.get("gpu") or "unknown"),
        "driver_version": str(hardware.get("driver_version") or "unknown"),
        "vram_gb": round(float(hardware.get("vram_gb") or 0), 1),
        "ram_gb": round(float(hardware.get("ram_gb") or 0), 1),
    }
    return ollama_context_policy.machine_profile_key(fingerprint)


def _canonical(name: Any) -> str:
    value = str(name or "").strip()
    return value[:-7] if value.endswith(":latest") else value


def load(path: Path = PROFILE_PATH) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 32:
        return None
    return payload


def resolve(
    hardware: dict[str, Any],
    installed_models: list[dict[str, Any]],
    *,
    path: Path = PROFILE_PATH,
) -> dict[str, Any]:
    """Retourne uniquement des gagnants encore lies au materiel et au digest exacts."""
    payload = load(path)
    if payload is None:
        return {"status": "missing", "winners": {}, "path": str(path)}
    if payload.get("machine_key") != machine_key(hardware):
        return {"status": "stale_hardware", "winners": {}, "path": str(path)}

    installed = {
        _canonical(item.get("name")): item
        for item in installed_models
        if _canonical(item.get("name"))
    }
    qualified: dict[str, dict[str, Any]] = {}
    for item in payload.get("candidates") or []:
        if not isinstance(item, dict) or item.get("status") != "qualified":
            continue
        model = _canonical(item.get("model"))
        current = installed.get(model)
        if current is None:
            continue
        expected_digest = str(item.get("model_digest") or "")
        current_digest = str(current.get("digest") or "")
        if not expected_digest or expected_digest != current_digest:
            continue
        repetitions = int(item.get("repetitions") or 0)
        success_rate = float(item.get("success_rate") or 0)
        warm_latency = float(item.get("median_warm_latency_ms") or 0)
        if repetitions < 3 or success_rate != 1.0 or warm_latency <= 0:
            continue
        for role in item.get("qualified_roles") or []:
            if role not in QUALIFIED_ROLES:
                continue
            previous = qualified.get(role)
            if previous is None or warm_latency < float(previous["median_warm_latency_ms"]):
                qualified[role] = {
                    "model": model,
                    "model_digest": current_digest,
                    "median_warm_latency_ms": warm_latency,
                    "repetitions": repetitions,
                    "success_rate": success_rate,
                }

    status = "qualified" if qualified else "no_valid_candidate"
    return {
        "status": status,
        "winners": qualified,
        "generated_at": payload.get("generated_at"),
        "ollama_version": payload.get("ollama_version"),
        "path": str(path),
    }


def apply_to_recommendation(
    recommendation: dict[str, Any],
    hardware: dict[str, Any],
    installed_models: list[dict[str, Any]],
    *,
    path: Path = PROFILE_PATH,
) -> dict[str, Any]:
    evidence = resolve(hardware, installed_models, path=path)
    for role, winner in evidence["winners"].items():
        model = str(winner["model"])
        recommendation.setdefault("chosen", {})[role] = model
        portfolio = recommendation.setdefault("portfolio", {}).setdefault(role, {})
        portfolio.update({
            "selected": model,
            "selected_source": "runtime_qualification",
            "runtime_qualification": winner,
        })
    return evidence
