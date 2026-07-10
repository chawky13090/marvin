"""
Auto-configuration des modèles selon la CAPACITÉ de la machine.

Marvin détecte la VRAM (GPU NVIDIA/AMD) ou la RAM (CPU), puis choisit le meilleur
modèle pour chaque profil (chat / agent / analysis / vision). S'exécute au démarrage
→ Marvin s'adapte tout seul quand on l'installe sur une autre machine.

Stratégie : on APPLIQUE le meilleur modèle DÉJÀ installé qui tient dans la VRAM,
et on RECOMMANDE de télécharger l'idéal s'il manque (jamais de download surprise).
"""
import subprocess

import database as db
from config import MODEL_PROFILES, OLLAMA_URL

# Tailles approximatives en Go (quantif. Q4) pour le repli « meilleur installé qui tient »
_SIZE = {
    "qwen2.5:3b": 2.0, "qwen2.5:7b": 4.7, "qwen2.5:14b": 9.0, "qwen2.5:32b": 20.0,
    "llama3.2:3b": 2.0, "hermes3:8b": 4.7, "qwen3:8b": 5.2, "qwen3:14b": 9.0,
    "mistral-nemo": 7.0, "mistral-small": 14.0,
    "llava-phi3": 3.0, "llava:7b": 4.7, "llava:13b": 8.0, "llama3.2-vision:11b": 8.0,
}

# Idéal par palier de VRAM (Go). Premier palier dont min_vram <= VRAM gagne.
_TIERS = [
    (24, {"chat": "qwen2.5:7b",  "agent": "qwen2.5:32b", "analysis": "qwen2.5:32b", "vision": "llava:13b"}),
    (15, {"chat": "qwen2.5:7b",  "agent": "qwen2.5:14b", "analysis": "qwen2.5:14b", "vision": "llava:13b"}),
    (9,  {"chat": "qwen2.5:7b",  "agent": "qwen2.5:14b", "analysis": "qwen2.5:14b", "vision": "llava:7b"}),
    (6,  {"chat": "qwen2.5:3b",  "agent": "qwen2.5:7b",  "analysis": "qwen2.5:7b",  "vision": "llava:7b"}),
    (3,  {"chat": "qwen2.5:3b",  "agent": "qwen2.5:7b",  "analysis": "qwen2.5:7b",  "vision": "llava-phi3"}),
]
_CPU = {"chat": "qwen2.5:3b", "agent": "qwen2.5:3b", "analysis": "qwen2.5:7b", "vision": "llava-phi3"}

# ── Modes de performance : règlent plusieurs leviers d'un coup, selon la machine ───────
# Chaque mode bundle : cible de modèles + nb d'outils envoyés au LLM + modèle Whisper (STT)
# + stratégie d'apprentissage (resident/dedicated) + mode de génération de docs
# + autorisation génération vidéo locale + cadence des tâches de fond (bg_scale)
# + parallélisme (concurrence des opérations par lots). Modèles TOUJOURS plafonnés par la VRAM.
# bg_scale : multiplie l'intervalle des tâches de fond (2.0 = 2× moins souvent / 0.5 = 2× plus souvent)
_MODES = {
    "eco": {
        "label": "🍃 Léger", "models": _CPU,
        "max_tools": 18, "whisper": "base", "learn": "resident", "doc": "rapide",
        "allow_video": False, "bg_scale": 2.0, "concurrency": 2,
        "web_depth": 1, "rag_k": 4, "ocr_max_pages": 5, "ocr_scale": 1.5, "history_depth": 10,
        "desc": "Empreinte minimale : petits modèles, peu d'outils, tâches de fond espacées. Machines modestes.",
    },
    "balanced": {
        "label": "⚖️ Équilibré", "models": None,   # None → idéal selon la VRAM (_ideal_for)
        "max_tools": 40, "whisper": "small", "learn": "resident", "doc": "rapide",
        "allow_video": False, "bg_scale": 1.0, "concurrency": 3,
        "web_depth": 2, "rag_k": 6, "ocr_max_pages": 15, "ocr_scale": 2.0, "history_depth": 16,
        "desc": "Bon compromis vitesse/qualité. Recommandé pour un GPU 4-8 Go.",
    },
    "performance": {
        "label": "🚀 Performance",
        "models": {"chat": "qwen2.5:7b", "agent": "qwen2.5:14b", "analysis": "qwen2.5:14b", "vision": "llava:7b"},
        "max_tools": 80, "whisper": "medium", "learn": "dedicated", "doc": "detaille",
        "allow_video": True, "bg_scale": 0.6, "concurrency": 6,
        "web_depth": 3, "rag_k": 8, "ocr_max_pages": 40, "ocr_scale": 2.5, "history_depth": 24,
        "desc": "Exploite une machine solide (GPU 8-16 Go) : modèles 14b, plus d'outils, vidéo locale, recherche + OCR plus profonds.",
    },
    "max": {
        "label": "🔥 Maximum",
        "models": {"chat": "qwen2.5:7b", "agent": "qwen2.5:32b", "analysis": "qwen2.5:32b", "vision": "llava:13b"},
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
        ram = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception:
        ram = 8.0
    nv = _nvidia_vram()
    if nv:
        return {"vendor": "nvidia", "vram_gb": nv[0], "gpu": nv[1], "ram_gb": ram}
    try:
        import local_video
        amd = local_video._detect_amd_gpu()
        if amd and amd.get("vram_gb"):
            return {"vendor": "amd", "vram_gb": amd["vram_gb"], "gpu": amd["name"], "ram_gb": ram}
    except Exception:
        pass
    return {"vendor": "cpu", "vram_gb": 0.0, "gpu": "CPU (pas de GPU détecté)", "ram_gb": ram}


def _ideal_for(hw: dict) -> dict:
    if hw["vendor"] == "cpu" or hw["vram_gb"] < 3:
        return _CPU
    for min_vram, profiles in _TIERS:
        if hw["vram_gb"] >= min_vram:
            return profiles
    return _TIERS[-1][1]


def recommend(hw: dict, installed: set, target: dict = None) -> dict:
    ideal = target or _ideal_for(hw)
    budget = hw["vram_gb"] if hw["vram_gb"] > 0 else max(3.0, hw["ram_gb"] * 0.4)
    chosen, to_pull = {}, []
    for prof, model in ideal.items():
        # On n'applique le modèle idéal QUE s'il est installé ET qu'il TIENT dans la VRAM.
        # (sinon, forcer un mode « Performance » sur une petite machine chargerait un 14b
        #  qui déborde sur le CPU = très lent. Le mode reste toujours plafonné par le matériel.)
        if model in installed and _SIZE.get(model, 99) <= budget + 1.0:
            chosen[prof] = model
            continue
        if model not in installed:
            to_pull.append(model)   # idéal manquant (téléchargeable) ; s'il est installé mais trop gros, inutile de le proposer
        # repli : meilleur modèle installé qui tient (gros pour agent/analysis, petit pour chat)
        fits = [m for m in installed if _SIZE.get(m, 99) <= budget + 1.0]
        if prof == "vision":   # la vision exige un modèle multimodal
            vis = [m for m in fits if any(k in m for k in ("llava", "vision", "minicpm", "bakllava"))]
            fits = vis or [m for m in installed if any(k in m for k in ("llava", "vision", "minicpm"))]
        if not fits:
            chosen[prof] = MODEL_PROFILES.get(prof, {}).get("model", "qwen2.5:3b")
            continue
        big = prof in ("agent", "analysis")
        fits.sort(key=lambda m: _SIZE.get(m, 99), reverse=big)
        chosen[prof] = fits[0]
    return {"ideal": ideal, "chosen": chosen, "to_pull": sorted(set(to_pull))}


async def _installed_models() -> set:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            names = set()
            for m in r.json().get("models", []):
                n = m["name"]
                names.add(n)
                if n.endswith(":latest"):   # « llava-phi3:latest » correspond aussi à « llava-phi3 »
                    names.add(n[:-len(":latest")])
            return names
    except Exception:
        return set()


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

    rec = recommend(hw, installed, mcfg["models"])
    for prof, model in rec["chosen"].items():
        if prof in MODEL_PROFILES and model:
            MODEL_PROFILES[prof]["model"] = model

    # Override manuel par profil (per-machine, dans data/ → distribuable) : permet d'épingler
    # un modèle précis (ex. tout en qwen2.5:14b sur une machine puissante). On n'applique que
    # si le modèle est réellement installé (sinon on garde le choix auto).
    try:
        overrides = db.get_setting("model_overrides") or {}
        if isinstance(overrides, dict):
            for prof, model in overrides.items():
                if prof in MODEL_PROFILES and model and (model in installed or (model + ":latest") in installed):
                    MODEL_PROFILES[prof]["model"] = model
                    rec["chosen"][prof] = model
    except Exception:
        pass

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

    summary = {"enabled": True, "hardware": hw, "applied": rec["chosen"],
               "ideal": rec["ideal"], "recommended_to_install": rec["to_pull"],
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
