"""Veille du catalogue de modèles Ollama Cloud (v2.524).

`model_market.RECOMMENDED_CLOUD_MODELS` et `DISCOVERABLE_CLOUD_MODELS` sont des tuples
codés en dur : `sync_recommended_cloud_models` s'assure qu'ils sont installés, mais rien
ne détecte l'apparition d'un nouveau modèle sur le catalogue Cloud réel. Constaté par
audit : `glm-5.1`, `gpt-oss:20b`, `nemotron-3-nano:30b` et `gemma4:31b` étaient déjà
disponibles côté Ollama sans figurer dans notre liste — sans intervention manuelle sur
ce fichier, le catalogue « de pointe » se périme silencieusement.

Ce module SIGNALE, il n'installe jamais rien et ne modifie jamais `model_market.py` :
une nouveauté détectée est un fait à examiner par un humain, pas une action autonome.
La source est `https://ollama.com/api/tags` — endpoint public officiel du fournisseur
(vérifié : 200, JSON, sans authentification), récupéré via `outbound_http.fetch_public`
qui épingle l'IP publique résolue et refuse les redirections, comme le reste du projet.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import outbound_http
from config import DATA_DIR
import model_market

CATALOG_URL = "https://ollama.com/api/tags"
# Convention Ollama : le marqueur cloud est ajouté en ":cloud" si le nom n'a pas
# encore de tag (ex. "deepseek-v4-pro" -> "deepseek-v4-pro:cloud"), ou en "-cloud"
# si un tag de taille existe déjà (ex. "qwen3.5:397b" -> "qwen3.5:397b-cloud"). Les
# deux formes coexistent dans `model_market.DISCOVERABLE_CLOUD_MODELS` : on les
# normalise toutes les deux pour comparer avec les noms bruts du catalogue distant.
_CLOUD_SUFFIX = re.compile(r"[:-]cloud$")
STATE_PATH = Path(DATA_DIR) / "model_catalog_watch.json"
# Une fois par jour suffit : c'est une veille, pas un polling temps réel, et ça
# borne la charge sur l'infrastructure du fournisseur.
MIN_INTERVAL_SECONDS = 24 * 3600


def _known_models() -> set[str]:
    """Modèles déjà couverts par le catalogue codé en dur, forme courte (sans suffixe cloud)."""
    return {_CLOUD_SUFFIX.sub("", name) for name in model_market.DISCOVERABLE_CLOUD_MODELS}


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _parse_catalog(raw: bytes) -> list[dict[str, Any]]:
    payload = json.loads(raw.decode("utf-8"))
    models = payload.get("models")
    if not isinstance(models, list):
        raise ValueError("réponse catalogue inattendue : champ 'models' absent")
    parsed = []
    for entry in models:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        parsed.append({
            "name": str(entry["name"]),
            "size": entry.get("size"),
            "parameter_size": (entry.get("details") or {}).get("parameter_size") or None,
        })
    return parsed


async def refresh(*, force: bool = False) -> dict[str, Any]:
    """Interroge le catalogue Cloud réel et signale les nouveautés. N'installe rien."""
    state = _load_state()
    last_run = float(state.get("last_run_epoch") or 0)
    if not force and (time.time() - last_run) < MIN_INTERVAL_SECONDS:
        return {"skipped": True, "reason": "too_soon", **state}

    try:
        response = await outbound_http.fetch_public(CATALOG_URL, max_bytes=2_000_000, timeout=15.0)
    except Exception as exc:
        # Une panne de veille ne doit jamais dégrader Marvin : on garde le dernier
        # état connu et on journalise l'échec sans jamais planter l'appelant.
        state["last_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        state["last_attempt_epoch"] = time.time()
        _write_state(state)
        return {"success": False, "error": state["last_error"]}

    if response.status_code != 200:
        state["last_error"] = f"HTTP {response.status_code}"
        state["last_attempt_epoch"] = time.time()
        _write_state(state)
        return {"success": False, "error": state["last_error"]}

    try:
        catalog = _parse_catalog(response.content)
    except Exception as exc:
        # Le fournisseur peut changer son format sans préavis : on le signale
        # explicitement plutôt que de planter ou d'ignorer silencieusement.
        state["last_error"] = f"parse_error: {type(exc).__name__}: {str(exc)[:200]}"
        state["last_attempt_epoch"] = time.time()
        _write_state(state)
        return {"success": False, "error": state["last_error"]}

    known = _known_models()
    seen_names = {item["name"] for item in catalog}
    new_models = sorted(
        (item for item in catalog if item["name"] not in known),
        key=lambda item: item["name"],
    )
    previously_flagged = {item["name"] for item in state.get("new_models", [])}
    now = time.time()
    result = {
        "success": True,
        "catalog_size": len(catalog),
        "known_size": len(known),
        "new_models": new_models,
        "newly_flagged": [item["name"] for item in new_models if item["name"] not in previously_flagged],
        "last_run_epoch": now,
        "last_run_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "last_error": None,
    }
    _write_state(result)
    return result


def status() -> dict[str, Any]:
    """État de la dernière veille, sans en déclencher une nouvelle (lecture seule)."""
    state = _load_state()
    if not state:
        return {"checked": False, "new_models": []}
    return {"checked": True, **state}


async def background_worker() -> None:
    """Boucle de fond bornée : une vérification par jour, jamais d'installation."""
    import asyncio

    await asyncio.sleep(120)  # laisser le démarrage se stabiliser d'abord
    while True:
        try:
            await refresh()
        except Exception:
            pass  # le worker ne doit jamais s'arrêter sur un incident réseau isolé
        await asyncio.sleep(3600)  # revérifie l'horloge toutes les heures ; MIN_INTERVAL filtre
