"""
Auto-configuration des modèles selon la CAPACITÉ de la machine.

Marvin détecte la VRAM (GPU NVIDIA/AMD) ou la RAM (CPU), puis choisit le meilleur
modèle pour chaque profil (chat / agent / analysis / vision). S'exécute au démarrage
→ Marvin s'adapte tout seul quand on l'installe sur une autre machine.

Stratégie : on APPLIQUE le meilleur modèle DÉJÀ installé qui tient dans la VRAM,
et on RECOMMANDE de télécharger l'idéal s'il manque (jamais de download surprise).
"""
import shutil
import subprocess

import database as db
import local_model_policy
from config import MODEL_PROFILES, OLLAMA_URL

# ── Modes de performance : règlent plusieurs leviers d'un coup, selon la machine ───────
# Chaque mode bundle : cible de modèles + nb d'outils envoyés au LLM + modèle Whisper (STT)
# + stratégie d'apprentissage (resident/dedicated) + mode de génération de docs
# + autorisation génération vidéo locale + cadence des tâches de fond (bg_scale)
# + parallélisme (concurrence des opérations par lots). Modèles TOUJOURS plafonnés par la VRAM.
# bg_scale : multiplie l'intervalle des tâches de fond (2.0 = 2× moins souvent / 0.5 = 2× plus souvent)
_MODES = {
    "eco": {
        "label": "🍃 Léger",
        "max_tools": 18, "whisper": "base", "learn": "resident", "doc": "rapide",
        "allow_video": False, "bg_scale": 2.0, "concurrency": 2,
        "web_depth": 1, "rag_k": 4, "ocr_max_pages": 5, "ocr_scale": 1.5, "history_depth": 10,
        "desc": "Empreinte minimale : petits modèles, peu d'outils, tâches de fond espacées. Machines modestes.",
    },
    "balanced": {
        "label": "⚖️ Équilibré",
        "max_tools": 40, "whisper": "small", "learn": "resident", "doc": "rapide",
        "allow_video": False, "bg_scale": 1.0, "concurrency": 3,
        "web_depth": 2, "rag_k": 6, "ocr_max_pages": 15, "ocr_scale": 2.0, "history_depth": 16,
        "desc": "Bon compromis vitesse/qualité. Recommandé pour un GPU 4-8 Go.",
    },
    "performance": {
        "label": "🚀 Performance",
        "max_tools": 80, "whisper": "medium", "learn": "dedicated", "doc": "detaille",
        "allow_video": True, "bg_scale": 0.6, "concurrency": 6,
        "web_depth": 3, "rag_k": 8, "ocr_max_pages": 40, "ocr_scale": 2.5, "history_depth": 24,
        "desc": "Exploite une machine solide (GPU 8-16 Go) : modèles 14b, plus d'outils, vidéo locale, recherche + OCR plus profonds.",
    },
    "max": {
        "label": "🔥 Maximum",
        "max_tools": 250, "whisper": "medium", "learn": "dedicated", "doc": "detaille",
        "allow_video": True, "bg_scale": 0.5, "concurrency": 10,
        "web_depth": 4, "rag_k": 12, "ocr_max_pages": 100, "ocr_scale": 3.0, "history_depth": 32,
        "desc": "Tout en puissance (GPU 24 Go+). Modèles 32b, tous les outils, recherche/OCR/mémoire au maximum.",
    },
}
_MODE_ORDER = ["eco", "balanced", "performance", "max"]


def pick_mode(hw: dict) -> str:
    """Mode par défaut conseillé selon le matériel détecté."""
    v = hw.get("vram_gb", 0)
    if hw.get("vendor") == "cpu" or v < 4:
        return "eco"
    if v >= 24:
        return "max"
    if v >= 9:
        return "performance"
    return "balanced"


def _nvidia_vram():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, creationflags=0x08000000)
        line = (out.stdout or "").strip().splitlines()[0]
        mb = int(line.split(",")[0].strip())
        name = line.split(",", 1)[1].strip()
        return round(mb / 1024, 1), name
    except Exception:
        return None


def detect_hardware() -> dict:
    try:
        import psutil
        memory = psutil.virtual_memory()
        ram = round(memory.total / 1024 ** 3, 1)
        ram_available = round(memory.available / 1024 ** 3, 1)
    except Exception:
        ram = 8.0
        ram_available = 4.0
    try:
        disk = shutil.disk_usage(str(local_model_policy.CATALOG_PATH.anchor))
        disk_free = int(disk.free)
    except OSError:
        disk_free = 0
    nv = _nvidia_vram()
    if nv:
        return {
            "vendor": "nvidia", "vram_gb": nv[0], "gpu": nv[1],
            "ram_gb": ram, "ram_available_gb": ram_available,
            "disk_free_bytes": disk_free,
        }
    try:
        import local_video
        amd = local_video._detect_amd_gpu()
        if amd and amd.get("vram_gb"):
            return {
                "vendor": "amd", "vram_gb": amd["vram_gb"], "gpu": amd["name"],
                "ram_gb": ram, "ram_available_gb": ram_available,
                "disk_free_bytes": disk_free,
            }
    except Exception:
        pass
    return {
        "vendor": "cpu", "vram_gb": 0.0, "gpu": "CPU (pas de GPU détecté)",
        "ram_gb": ram, "ram_available_gb": ram_available,
        "disk_free_bytes": disk_free,
    }


async def _installed_models() -> list[dict]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            models = []
            for m in r.json().get("models", []):
                models.append({
                    "name": str(m.get("name") or ""),
                    "size_bytes": int(m.get("size") or 0),
                    "parameter_size": str((m.get("details") or {}).get("parameter_size") or ""),
                    "quantization": str((m.get("details") or {}).get("quantization_level") or ""),
                    "modified_at": str(m.get("modified_at") or ""),
                })
            return models
    except Exception:
        return []


async def _unload_orphan_models(applied: dict):
    """Décharge de la VRAM les modèles chargés qui ne sont plus assignés à aucun profil
    (ex : passer de 'Maximum' 32b à 'Léger' libère le 32b tout de suite). Best-effort.
    On garde l'embedder (nomic) et tous les modèles encore utilisés."""
    import httpx
    keep = set()
    for prof in MODEL_PROFILES.values():
        m = prof.get("model")
        if m:
            keep.add(m); keep.add(m + ":latest"); keep.add(m.replace(":latest", ""))
    for m in (applied or {}).values():
        if m:
            keep.add(m); keep.add(m + ":latest")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            loaded = (await c.get(f"{OLLAMA_URL}/api/ps")).json().get("models", [])
            for m in loaded:
                name = m.get("name", "")
                if not name or name in keep:
                    continue
                if "embed" in name or "nomic" in name:   # ne jamais décharger l'embedder
                    continue
                try:
                    await c.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0})
                except Exception:
                    pass
    except Exception:
        pass


async def apply_auto_config(force: bool = False) -> dict:
    """Détecte le matériel, choisit le MODE (auto ou forcé), applique les modèles ET les
    leviers d'optimisation du mode (nb d'outils, Whisper, apprentissage, génération docs)."""
    enabled = db.get_setting("auto_model_config")
    if enabled is None:
        enabled = True
    if not enabled and not force:
        return {"enabled": False}
    installed = await _installed_models()
    hw = detect_hardware()

    # Mode : override utilisateur ('eco'|'balanced'|'performance'|'max') sinon auto selon le matériel
    auto_mode = pick_mode(hw)
    override = db.get_setting("perf_mode")
    mode = override if override in _MODES else auto_mode
    mcfg = _MODES[mode]

    rec = local_model_policy.recommend(hw, installed)
    for prof, model in rec["chosen"].items():
        if prof in MODEL_PROFILES and model:
            MODEL_PROFILES[prof]["model"] = model

    # Un override est une préférence, jamais une permission de dépasser le budget matériel.
    rejected_overrides = []
    try:
        overrides = db.get_setting("model_overrides") or {}
        if isinstance(overrides, dict):
            for prof, model in overrides.items():
                if prof not in MODEL_PROFILES or not model:
                    continue
                allowed, reason = local_model_policy.override_allowed(
                    str(model), str(prof), hw, installed,
                )
                if allowed:
                    MODEL_PROFILES[prof]["model"] = model
                    rec["chosen"][prof] = model
                else:
                    rejected_overrides.append({
                        "profile": str(prof)[:50],
                        "model": str(model)[:200],
                        "reason": reason,
                    })
    except Exception:
        rejected_overrides.append({
            "profile": "*", "model": "*",
            "reason": "overrides illisibles ou catalogue indisponible",
        })

    # Libère la VRAM des modèles qui ne servent plus (changement de mode) — best-effort.
    try:
        await _unload_orphan_models(rec["chosen"])
    except Exception:
        pass

    # Génération vidéo locale : autorisée par le mode ET supportée par le GPU (CUDA + VRAM).
    # La vidéo IA locale exige NVIDIA/CUDA ; ~4 Go minimum (limité), confortable ≥6 Go.
    video_enabled = bool(mcfg.get("allow_video") and hw.get("vendor") == "nvidia" and hw.get("vram_gb", 0) >= 4)

    # Leviers comportementaux pilotés par le mode (lus ailleurs : agent.py, tools.py, main.py)
    db.set_setting("max_tools", mcfg["max_tools"])
    db.set_setting("learn_strategy", mcfg["learn"])
    db.set_setting("doc_default_mode", mcfg["doc"])
    db.set_setting("whisper_model", mcfg["whisper"])
    db.set_setting("video_gen_enabled", video_enabled)
    db.set_setting("bg_scale", float(mcfg.get("bg_scale", 1.0)))
    db.set_setting("task_concurrency", int(mcfg.get("concurrency", 3)))
    db.set_setting("web_depth", int(mcfg.get("web_depth", 2)))
    db.set_setting("rag_k", int(mcfg.get("rag_k", 6)))
    db.set_setting("ocr_max_pages", int(mcfg.get("ocr_max_pages", 15)))
    db.set_setting("ocr_scale", float(mcfg.get("ocr_scale", 2.0)))
    db.set_setting("history_depth", int(mcfg.get("history_depth", 16)))

    recommendations = [
        item for item in rec["downloads"] if item.get("disk_ready") is True
    ]
    summary = {"enabled": True, "hardware": hw, "applied": rec["chosen"],
               "portfolio": rec["portfolio"],
               "recommended_to_install": [item["model"] for item in recommendations],
               "download_plan": rec["downloads"],
               "rejected_overrides": rejected_overrides,
               "model_memory_budget_gb": rec["memory_budget_gb"],
               "catalog_schema": rec["catalog_schema"],
               "catalog_updated_at": rec["catalog_updated_at"],
               "mode": mode, "mode_label": mcfg["label"], "mode_desc": mcfg["desc"],
               "auto_mode": auto_mode, "is_override": bool(override in _MODES),
               "levers": {"max_tools": mcfg["max_tools"], "whisper": mcfg["whisper"],
                          "learn": mcfg["learn"], "doc": mcfg["doc"],
                          "video_gen": video_enabled, "bg_scale": mcfg.get("bg_scale", 1.0),
                          "concurrency": mcfg.get("concurrency", 3),
                          "web_depth": mcfg.get("web_depth", 2), "rag_k": mcfg.get("rag_k", 6),
                          "ocr_max_pages": mcfg.get("ocr_max_pages", 15), "ocr_scale": mcfg.get("ocr_scale", 2.0),
                          "history_depth": mcfg.get("history_depth", 16)},
               "modes": [{"key": k, "label": _MODES[k]["label"], "desc": _MODES[k]["desc"]} for k in _MODE_ORDER]}
    db.set_setting("auto_config", summary)
    return summary
