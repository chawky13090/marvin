"""
local_video.py — Génération vidéo IA 100% locale (CogVideoX via HuggingFace Diffusers).
Les modèles sont téléchargés automatiquement la première fois (~9–20 Go selon le modèle).

Compatibilité GPU :
  GTX 1650 / 4 Go VRAM → CogVideoX-2B avec cpu_offload (recommandé)
  RTX 3070+ / 8 Go+     → CogVideoX-2B full GPU
  RTX 3090+ / 16 Go+    → CogVideoX-5B full GPU
"""
import uuid
import json
import asyncio
import threading
import concurrent.futures
import os
import time
import datetime as _dt
from pathlib import Path

# ── Répertoire de sortie ──────────────────────────────────────────────────────

_VIDEO_DIR = Path(__file__).parent / "generated_videos"
_VIDEO_DIR.mkdir(exist_ok=True)

# ── Catalogue des modèles locaux ──────────────────────────────────────────────

LOCAL_MODELS = {
    "animatelcm": {
        "name": "AnimateLCM ⚡ Turbo",
        "model_id": "emilianJR/epiCRealism",                 # base SD1.5 réaliste
        "motion_adapter_id": "wangfuyun/AnimateLCM",          # motion adapter + LoRA LCM
        "lora_weight": "AnimateLCM_sd15_t2v_lora.safetensors",
        "pipeline_class": "AnimateDiffPipeline",
        "mode": "t2v",
        "description": "Texte → Vidéo · few-step LCM · durée réglable · qualité réglable (256/384/512)",
        "size_gb": 4,
        "min_vram_gb": 3,
        "full_vram_gb": 6,
        "steps": 6,             # 6 étapes : bon compromis adhérence/vitesse (LCM)
        "frames": 16,           # base ; ajusté selon la durée demandée (max 32)
        "max_frames": 32,       # limite du motion adapter (motion_max_seq_length)
        "fps": 8,               # fps natif de génération
        "guidance": 2.5,        # ↑ pour mieux respecter le prompt (était 1.8 → sujet ignoré)
        "width": 512,
        "height": 512,
        "max_seconds": 1200,    # budget temps dur : 20 min → annulation auto (anti-blocage)
        "recommended": True,
    },
    "cogvideox-2b": {
        "name": "CogVideoX-2B",
        "model_id": "THUDM/CogVideoX-2b",
        "pipeline_class": "CogVideoXPipeline",
        "mode": "t2v",
        "description": "Texte → Vidéo 4–6s · Recommandé pour 4 Go VRAM (sequential offload)",
        "size_gb": 9,
        "min_vram_gb": 4,          # avec enable_sequential_cpu_offload
        "full_vram_gb": 8,         # pour charger entièrement sur GPU
        "steps": 50,
        "frames": 33,              # réduit de 49 à 33 pour économiser la VRAM (~4s@8fps)
        "fps": 8,
        "guidance": 6.0,
        "max_seconds": 1500,       # 25 min max sur petit GPU → annulation auto
        "vram_frames": {           # frames recommandés selon VRAM disponible
            4: 9,                  # 4 Go → 9 frames (1s) — safe, évite cudaErrorNotReady
            5: 13,                 # 5 Go → 13 frames (1.6s)
            6: 17,                 # 6 Go → 17 frames (2s)
            8: 25,                 # 8 Go → 25 frames (3s)
            12: 33,                # 12 Go → 33 frames (4s)
        },
    },
    "cogvideox-5b": {
        "name": "CogVideoX-5B",
        "model_id": "THUDM/CogVideoX-5b",
        "pipeline_class": "CogVideoXPipeline",
        "mode": "t2v",
        "description": "Texte → Vidéo 6s haute qualité · 10 Go VRAM recommandé",
        "size_gb": 20,
        "min_vram_gb": 6,          # avec offload agressif
        "full_vram_gb": 16,
        "steps": 50,
        "frames": 49,
        "fps": 8,
        "guidance": 6.0,
        "max_seconds": 2400,
    },
    "cogvideox-5b-i2v": {
        "name": "CogVideoX-5B I2V",
        "model_id": "THUDM/CogVideoX-5b-I2V",
        "pipeline_class": "CogVideoXImageToVideoPipeline",
        "mode": "i2v",
        "description": "Image → Vidéo 6s haute qualité · 10 Go VRAM recommandé",
        "size_gb": 20,
        "min_vram_gb": 6,
        "full_vram_gb": 16,
        "steps": 50,
        "frames": 49,
        "fps": 8,
        "guidance": 6.0,
        "max_seconds": 2400,
    },
}

# ── État global du pipeline chargé ───────────────────────────────────────────

_state: dict = {"model_key": None, "pipeline": None}
_pipeline_lock = threading.Lock()
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="local_video"
)

# Annulation coopérative : levée par /api/video/cancel, vérifiée entre chaque étape.
_cancel_event = threading.Event()


class _GenAborted(Exception):
    """Levée pour annuler proprement une génération (timeout ou annulation manuelle)."""


def request_cancel():
    """Demande l'annulation de la génération en cours (vérifiée entre les étapes)."""
    _cancel_event.set()


# ── Infos matériel ────────────────────────────────────────────────────────────

# Cache device info à DURÉE DE VIE COURTE (TTL), pas figé pour toujours : l'utilisateur
# change souvent de carte graphique (test de cartes clients) → il faut que Marvin s'en
# rende compte SANS redémarrer le backend. `import torch` est coûteux (3-5s) seulement
# au tout premier appel du process (Python le garde en cache dans sys.modules) ; les
# appels suivants à torch.cuda.is_available() sont rapides → un TTL court est peu coûteux.
_device_info_cache: dict | None = None
_device_info_ts: float = 0.0
_DEVICE_INFO_TTL = 20.0   # secondes — assez court pour être "temps réel", assez long pour ne pas spammer


def _detect_directml_gpu() -> dict | None:
    """Détecte un GPU utilisable via DirectML (Microsoft) : c'est la SEULE voie native
    pour faire tourner PyTorch sur un GPU AMD sous Windows (ROCm = Linux uniquement).
    Fonctionne aussi sur Intel/NVIDIA en secours si CUDA est indisponible pour une raison X.
    Nécessite le paquet optionnel `torch-directml` (voir requirements-video.txt)."""
    try:
        import torch_directml
        if torch_directml.device_count() < 1:
            return None
        idx = 0
        name = torch_directml.device_name(idx)
        return {"index": idx, "name": name}
    except Exception:
        return None


def _detect_amd_gpu() -> dict | None:
    """Détecte une carte AMD/Radeon via Windows (registre + WMI). Couvre la quasi-totalité
    des modèles AMD (RX, Radeon, Vega, ATI, APU). Retourne {name, vram_gb} ou None."""
    import subprocess
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    ps = (
        "$cards=@();"
        "Get-ChildItem 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}' -EA SilentlyContinue | ForEach-Object {"
        " $p=Get-ItemProperty $_.PSPath -EA SilentlyContinue;"
        " if ($p.DriverDesc) { $cards += [pscustomobject]@{Name=$p.DriverDesc; Vram=[int64]($p.'HardwareInformation.qwMemorySize')} } };"
        "if (-not $cards) { Get-CimInstance Win32_VideoController -EA SilentlyContinue | ForEach-Object { $cards += [pscustomobject]@{Name=$_.Name; Vram=[int64]$_.AdapterRAM} } }"
        ";$cards | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=8, creationflags=flags,
                             encoding="utf-8", errors="replace").stdout.strip()
        if not out:
            return None
        import json as _json
        data = _json.loads(out)
        if isinstance(data, dict):
            data = [data]
        amd_kw = ("amd", "radeon", "rx ", "vega", "ati ", "firepro", "instinct")
        best = None
        for c in data:
            nm = (c.get("Name") or "").strip()
            if nm and any(k in nm.lower() for k in amd_kw):
                vram = round((c.get("Vram") or 0) / 1024 ** 3, 1)
                if best is None or vram > best["vram_gb"]:
                    best = {"name": nm, "vram_gb": vram}
        return best
    except Exception:
        return None


def get_device_info(force: bool = False) -> dict:
    """Détecte CUDA(NVIDIA)/DirectML(AMD/Intel)/CPU + VRAM. Mis en cache avec un TTL COURT
    (20s) — pas figé pour toujours : redétecte automatiquement un changement de carte
    graphique sans redémarrage du backend. `force=True` force une redétection immédiate
    (utilisé par l'outil `pc_gpu_status` juste après un changement de carte)."""
    global _device_info_cache, _device_info_ts
    now = time.monotonic()
    if not force and _device_info_cache is not None and (now - _device_info_ts) < _DEVICE_INFO_TTL:
        return _device_info_cache

    vendor, backend = "cpu", "cpu"
    try:
        import torch
        cuda = torch.cuda.is_available()
        if cuda:
            name = torch.cuda.get_device_name(0)
            vram = round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 1)
            vendor, backend = "nvidia", "cuda"
        else:
            name, vram = "CPU", 0
    except Exception:
        cuda, name, vram = False, "CPU", 0

    # Pas de CUDA ? Cherche un GPU utilisable via DirectML (AMD natif sous Windows, ou
    # Intel/NVIDIA en secours) AVANT de se rabattre sur le simple affichage AMD.
    dml = None
    if not cuda:
        dml = _detect_directml_gpu()
        if dml:
            amd_probe = _detect_amd_gpu()   # pour un nom propre + VRAM si c'est bien une AMD
            name = (amd_probe or {}).get("name") or dml["name"]
            vram = (amd_probe or {}).get("vram_gb") or 0
            vendor = "amd" if amd_probe else "directml"
            backend = "directml"

    # Sinon, juste DÉTECTER une carte AMD pour l'affichage/diagnostic (pas de compute).
    amd = None
    if not cuda and not dml:
        amd = _detect_amd_gpu()
        if amd:
            name, vram, vendor = amd["name"], amd["vram_gb"], "amd"

    video_gen_supported = cuda or (backend == "directml")
    info = {
        "cuda": cuda, "device_name": name, "vram_gb": vram,
        "vendor": vendor, "is_amd": vendor == "amd", "backend": backend,
        "video_gen_supported": video_gen_supported,
        "amd_compute_native": backend == "directml",
        "detected_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    # Précision optimale (bf16 sur GTX 16xx/10xx pour éviter les vidéos noires ; float32
    # par défaut sur DirectML — le support fp16 varie trop selon le GPU pour le présumer).
    try:
        dt = _optimal_dtype(info)
        info["precision"] = {"torch.bfloat16": "bf16", "torch.float16": "fp16",
                             "torch.float32": "fp32"}.get(str(dt), str(dt))
    except Exception:
        info["precision"] = "fp32"

    _device_info_cache, _device_info_ts = info, now
    return info


def refresh_device_info() -> dict:
    """Force une redétection immédiate (après un changement de carte graphique)."""
    return get_device_info(force=True)


def _spec_repo_ids(spec: dict) -> list[str]:
    """Tous les dépôts HF nécessaires pour un modèle (base + motion adapter éventuel)."""
    ids = [spec["model_id"]]
    if spec.get("motion_adapter_id"):
        ids.append(spec["motion_adapter_id"])
    return ids


def _smooth_retime(in_path: str, out_path: str, target_duration: float,
                   src_fps: int, n_frames: int, target_fps: int = 24) -> bool:
    """
    Étire/compresse le clip à `target_duration` secondes ET le lisse à `target_fps`
    via interpolation de mouvement (ffmpeg minterpolate). Permet une durée LIBRE
    à partir des frames générées (le modèle ne produit que 16-32 frames).
    Retourne True si succès.
    """
    import subprocess
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return False
    src_duration = max(n_frames / float(src_fps), 0.1)
    # ×1.06 compense la légère perte de durée introduite par minterpolate (~5,5%)
    # mesurée empiriquement → la durée finale colle à la cible demandée.
    ratio = max((target_duration / src_duration) * 1.06, 0.05)   # >1 = ralentit (plus long)
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    # setpts étire la durée ; minterpolate régénère des frames intermédiaires fluides
    vf = (f"setpts={ratio:.5f}*PTS,"
          f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
    cmd = [exe, "-y", "-i", in_path, "-vf", vf,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "faststart", out_path]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=180, creationflags=flags)
        return p.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception:
        return False


def _optimal_dtype(dev: dict):
    """
    Choisit le dtype optimal selon le GPU.
    ⚠️ Les GTX 16xx (Turing) et 10xx (Pascal) ont un BUG fp16 : conv2d renvoie NaN
       → vidéos NOIRES. On utilise bfloat16 (même mémoire que fp16, plage = fp32,
       PAS de NaN) si supporté, sinon float32.
    Sur les cartes récentes (RTX), fp16 est rapide et correct → on le garde.
    """
    import torch
    if not dev.get("cuda"):
        return torch.float32
    name = (dev.get("device_name") or "").upper()
    fp16_broken = any(t in name for t in ("GTX 16", "GTX 10", "GTX 9", " MX", "QUADRO P", "QUADRO T"))
    if fp16_broken:
        try:
            x = torch.randn(1, 8, 8, 8, dtype=torch.bfloat16, device="cuda")
            w = torch.randn(8, 8, 3, 3, dtype=torch.bfloat16, device="cuda")
            y = torch.nn.functional.conv2d(x, w, padding=1)
            torch.cuda.synchronize()
            if not torch.isnan(y).any():
                return torch.bfloat16
        except Exception:
            pass
        return torch.float32
    return torch.float16


def is_model_cached(model_id) -> bool:
    """Vérifie si le(s) dépôt(s) sont présents dans le cache HuggingFace local.
    Accepte un str (un dépôt) ou une liste de dépôts (tous requis)."""
    ids = [model_id] if isinstance(model_id, str) else list(model_id)
    try:
        from huggingface_hub import scan_cache_dir
        cached = {repo.repo_id for repo in scan_cache_dir().repos}
        return all(i in cached for i in ids)
    except Exception:
        return False


def is_spec_cached(spec: dict) -> bool:
    """Vrai si tous les dépôts d'un modèle sont en cache."""
    return is_model_cached(_spec_repo_ids(spec))


def _vram_hint(dev: dict, spec: dict) -> tuple[bool, str]:
    """Retourne (utilisable, message) selon le GPU disponible."""
    is_lcm = spec.get("pipeline_class") == "AnimateDiffPipeline"

    if not dev["cuda"]:
        if is_lcm:
            return True, "🐌 CPU uniquement — lent mais faisable (~5–15 min/vidéo)"
        return True, "🐌 CPU uniquement — TRÈS lent (30–120 min) — préférez AnimateLCM"

    vram = dev["vram_gb"]
    min_v  = spec["min_vram_gb"]
    full_v = spec["full_vram_gb"]

    if vram < min_v:
        return False, f"⚠️ VRAM insuffisante — besoin de {min_v} Go min (vous avez {vram} Go)"

    # AnimateLCM : few-step, optimisé bf16 + sequential-offload selon le GPU
    if is_lcm:
        if vram <= 4:
            return True, f"⚡ Optimisé {vram} Go — 256px, bf16, streaming (~1-1,5 min/vidéo)"
        if vram <= 6:
            return True, f"⚡ Rapide — 384px sur {vram} Go (~2-3 min/vidéo)"
        return True, f"🚀 Très rapide — 512px sur {vram} Go (~30 s–1 min/vidéo)"

    # CogVideoX : lourd
    if vram <= 6:
        return True, (f"🐢 Lent sur {vram} Go (sequential offload, ~20–40 min/vidéo) — "
                      f"AnimateLCM est BEAUCOUP plus rapide")
    if vram < full_v:
        return True, f"⚡ CPU-offload sur {vram} Go (~3–8 min/vidéo)"
    return True, f"🚀 GPU full — {vram} Go VRAM (~1–3 min/vidéo)"


def get_models_status() -> dict:
    """Retourne les infos de chaque modèle (cache, device, vram hint)."""
    dev = get_device_info()
    result = {}
    for key, spec in LOCAL_MODELS.items():
        ok, hint = _vram_hint(dev, spec)
        result[key] = {
            **spec,
            "cached": is_spec_cached(spec),
            "vram_ok": ok,
            "vram_hint": hint,
        }
    return {"models": result, "device": dev}


# ── Chargement pipeline avec optimisations VRAM ───────────────────────────────

def _apply_memory_optimizations(pipe, vram_gb: float, full_vram_gb: int, is_lcm: bool = False):
    """
    Optimisations mémoire adaptées au GPU disponible.
    - AnimateLCM (SD1.5, léger) : model_cpu_offload même sur 4 Go → RAPIDE.
    - CogVideoX (lourd) sur <=5 Go : sequential_cpu_offload (lent mais évite l'OOM).
    """
    import os, torch, gc

    # ── Variables d'environnement CUDA anti-fragmentation ─────────────────────
    # expandable_segments:True : permet au gestionnaire de mémoire CUDA d'utiliser
    # des segments extensibles pour éviter la fragmentation (recommandé par PyTorch)
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

    # Forcer la libération de toute mémoire Python et CUDA avant le chargement
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    if is_lcm:
        # ⚡ DÉCOUVERTE CLÉ (benchmark) : sur 4 Go, model_cpu_offload garde tout le
        # UNet (~2.8 Go) résident → débordement en MÉMOIRE PARTAGÉE Windows (PCIe)
        # → 108 s/étape. sequential_cpu_offload streame les couches (pic ~2.6 Go,
        # PAS de débordement) → 12 s/étape, soit ~9x plus rapide.
        if vram_gb >= full_vram_gb:
            pipe.to("cuda")                    # gros GPU : tout sur GPU = plus rapide
        else:
            pipe.enable_sequential_cpu_offload()  # petit GPU : streaming, pas de spill
    elif vram_gb <= 5:
        # sequential_cpu_offload : offload layer-by-layer (pic VRAM ~1.5 Go max)
        # C'est le mode le plus économe pour les GPU 4 Go (mais lent)
        pipe.enable_sequential_cpu_offload()
    elif vram_gb < full_vram_gb:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")

    # Attention slicing pour CogVideoX uniquement (lourd). Pour AnimateLCM on installe
    # explicitement un SlicedAttnProcessor au moment de l'inférence (slice_size réglé
    # finement) ; appeler enable_attention_slicing(1) ici le forcerait à 1-par-1 → 3x
    # plus lent. On NE l'active donc PAS pour le chemin LCM.
    if not is_lcm and vram_gb <= 6 and hasattr(pipe, "enable_attention_slicing"):
        pipe.enable_attention_slicing(1)  # 1 = most aggressive slicing

    # VAE slicing : décode les frames par chunks au lieu de tout en une fois (peu coûteux en vitesse)
    if hasattr(pipe, "enable_vae_slicing"):
        pipe.enable_vae_slicing()

    # VAE tiling pour les grandes résolutions — utile surtout pour CogVideoX
    if not is_lcm and hasattr(pipe, "enable_vae_tiling"):
        pipe.enable_vae_tiling()

    # Deuxième nettoyage CUDA après configuration
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        gc.collect()


# ── Fonction bloquante : téléchargement + chargement + génération ─────────────

def _run_generation(
    model_key: str,
    prompt: str,
    num_steps: int,
    num_frames: int,
    fps: int,
    guidance: float,
    image_path: str | None,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    duration: float | None = None,
    resolution: int | None = None,
    seed: int | None = None,
    negative_prompt: str | None = None,
) -> None:
    """
    Exécuté dans le thread dédié.
    1. Télécharge le modèle si absent du cache.
    2. Charge le pipeline (réutilise si déjà en mémoire).
    3. Génère la vidéo avec callback de progression par étape.
    4. Exporte en MP4 dans generated_videos/.
    """
    import torch

    def _put(payload: dict):
        asyncio.run_coroutine_threadsafe(queue.put(payload), loop)

    # Réinitialise le drapeau d'annulation pour ce nouveau job
    _cancel_event.clear()

    # Endurance : nettoie les fichiers temporaires _raw_ laissés par un crash
    # antérieur (un seul job à la fois → tout _raw_ existant est obsolète).
    try:
        for _stale in _VIDEO_DIR.glob("_raw_*.mp4"):
            try: _stale.unlink()
            except Exception: pass
    except Exception:
        pass

    try:
        spec = LOCAL_MODELS[model_key]
        model_id = spec["model_id"]

        with _pipeline_lock:
            # ── 1. Téléchargement (base + motion adapter éventuel) ────────────
            repo_ids = _spec_repo_ids(spec)
            missing = [r for r in repo_ids if not is_model_cached(r)]
            if missing:
                _put({
                    "status": "downloading",
                    "progress": 0,
                    "message": (
                        f"⬇️ Téléchargement de {spec['name']} "
                        f"(~{spec['size_gb']} Go depuis HuggingFace)… "
                        "Une seule fois, puis mis en cache."
                    ),
                })
                from huggingface_hub import snapshot_download
                for r in missing:
                    if _cancel_event.is_set():
                        raise _GenAborted("Annulé pendant le téléchargement.")
                    snapshot_download(repo_id=r)
                _put({"status": "downloading", "progress": 1, "message": "✅ Téléchargement terminé."})

            # ── 2. Libérer l'ancien pipeline si modèle différent ──────────────
            if _state["model_key"] != model_key and _state["pipeline"] is not None:
                del _state["pipeline"]
                _state["pipeline"] = None
                _state["model_key"] = None
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

            # ── 3. Charger le pipeline ────────────────────────────────────────
            if _state["pipeline"] is None:
                _put({
                    "status": "loading",
                    "progress": 2,
                    "message": f"🔧 Chargement de {spec['name']} en mémoire…",
                })

                dev = get_device_info()
                dtype = _optimal_dtype(dev)   # bf16 sur GTX 16xx/10xx (fix vidéos noires)
                pc    = spec["pipeline_class"]

                if pc == "CogVideoXPipeline":
                    from diffusers import CogVideoXPipeline
                    pipe = CogVideoXPipeline.from_pretrained(model_id, torch_dtype=dtype)

                elif pc == "CogVideoXImageToVideoPipeline":
                    from diffusers import CogVideoXImageToVideoPipeline
                    pipe = CogVideoXImageToVideoPipeline.from_pretrained(model_id, torch_dtype=dtype)

                elif pc == "AnimateDiffPipeline":
                    # AnimateLCM : SD1.5 + motion adapter + LoRA LCM (few-step, rapide)
                    from diffusers import AnimateDiffPipeline, MotionAdapter, LCMScheduler
                    adapter = MotionAdapter.from_pretrained(
                        spec["motion_adapter_id"], torch_dtype=dtype)
                    pipe = AnimateDiffPipeline.from_pretrained(
                        model_id, motion_adapter=adapter, torch_dtype=dtype)
                    # Scheduler LCM : permet la génération en 4-8 étapes
                    pipe.scheduler = LCMScheduler.from_config(
                        pipe.scheduler.config, beta_schedule="linear")
                    # LoRA LCM pour l'accélération
                    pipe.load_lora_weights(
                        spec["motion_adapter_id"],
                        weight_name=spec["lora_weight"],
                        adapter_name="lcm-lora")
                    pipe.set_adapters(["lcm-lora"], [0.8])

                else:
                    raise ValueError(f"Pipeline inconnue : {pc}")

                # Appliquer les optimisations mémoire
                is_lcm = (pc == "AnimateDiffPipeline")
                if dev["cuda"]:
                    _apply_memory_optimizations(pipe, dev["vram_gb"], spec["full_vram_gb"], is_lcm=is_lcm)
                    _put({
                        "status": "loading",
                        "progress": 3,
                        "message": (
                            f"✅ {spec['name']} chargé sur {dev['device_name']} "
                            f"({'CPU-offload' if dev['vram_gb'] < spec['full_vram_gb'] else 'GPU complet'})"
                        ),
                    })
                else:
                    pipe.enable_model_cpu_offload()
                    if hasattr(pipe, "enable_vae_slicing"):
                        pipe.enable_vae_slicing()

                _state["pipeline"] = pipe
                _state["model_key"] = model_key

            pipe = _state["pipeline"]

        # ── 4. Callback de progression par étape (avec timeout + annulation + ETA) ─
        # IMPORTANT: do NOT call torch.cuda.empty_cache() inside this callback.
        # It interferes with async CUDA operations and causes "device not ready" errors,
        # especially with enable_sequential_cpu_offload. Only update progress here.
        import time as _time
        max_seconds = spec.get("max_seconds", 1800)
        _infer_start = {"t": None}

        def _step_cb(p, step, ts, kwargs):
            now = _time.monotonic()
            if _infer_start["t"] is None:
                _infer_start["t"] = now
            elapsed = now - _infer_start["t"]

            # Annulation manuelle (bouton Annuler)
            if _cancel_event.is_set():
                raise _GenAborted("Génération annulée par l'utilisateur.")
            # Budget temps dur : empêche tout blocage de plusieurs heures
            if elapsed > max_seconds:
                raise _GenAborted(
                    f"Temps dépassé ({int(elapsed)}s > {max_seconds}s). "
                    f"Génération interrompue automatiquement pour éviter un blocage. "
                    f"Essayez AnimateLCM (rapide) ou réduisez les étapes/frames."
                )

            done = step + 1
            pct = max(5, int(5 + (done / num_steps) * 90))
            # ETA : extrapolation linéaire sur le temps moyen par étape
            eta = None
            if done >= 1:
                per_step = elapsed / done
                eta = int(per_step * (num_steps - done))
            _put({
                "status": "processing",
                "step": done,
                "total_steps": num_steps,
                "progress": pct,
                "eta_seconds": eta,
                "elapsed_seconds": int(elapsed),
            })
            return kwargs

        # Pre-inference: aggressive CUDA cleanup to maximize free VRAM
        # ⚠️ NE PAS activer CUDA_LAUNCH_BLOCKING : il force chaque kernel à être
        #    synchrone → catastrophique pour l'attention découpée (des milliers de
        #    petits kernels) → ralentit la génération de plusieurs ordres de grandeur.
        import gc as _gc
        os.environ.pop("CUDA_LAUNCH_BLOCKING", None)

        _gc.collect()
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            free_vram = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)
            free_gb = free_vram / 1024**3
            _put({
                "status": "processing",
                "step": 0,
                "total_steps": num_steps,
                "progress": 5,
                "message": f"🎬 Génération des frames… (VRAM libre : {free_gb:.1f} Go)",
            })
        else:
            _put({
                "status": "processing",
                "step": 0,
                "total_steps": num_steps,
                "progress": 5,
                "message": "🎬 Génération des frames (mode CPU)…",
            })

        # ── 5. Inférence ──────────────────────────────────────────────────────
        # Clamp num_frames à un maximum SÛR pour la VRAM (CogVideoX sur petit GPU).
        # CORRECTIF : ce clamp s'applique MÊME si le frontend a fourni une valeur,
        # car auparavant la sécurité 4 Go (9 frames) n'était jamais appliquée → OOM.
        dev = get_device_info()
        vram_frames = spec.get("vram_frames")
        if dev["cuda"] and vram_frames:
            vram = dev["vram_gb"]
            safe_max = spec["frames"]
            for threshold in sorted(vram_frames.keys()):
                if vram <= threshold:
                    safe_max = vram_frames[threshold]
                    break
            if num_frames is None:
                num_frames = safe_max
            elif num_frames > safe_max:
                _put({
                    "status": "processing", "progress": 5,
                    "message": f"⚠️ Frames limités à {safe_max} (sécurité VRAM {vram} Go) "
                               f"pour éviter un plantage mémoire.",
                })
                num_frames = safe_max
        elif num_frames is None:
            num_frames = spec["frames"]

        # ── Durée libre (AnimateLCM) : nb de frames natives selon la durée ────
        # Le motion adapter génère 16-32 frames de mouvement réel ; on en génère
        # autant que possible (≈ durée × fps natif), puis on retime à la durée
        # exacte avec interpolation de mouvement (étape d'export).
        is_lcm_gen = spec.get("pipeline_class") == "AnimateDiffPipeline"
        if is_lcm_gen and duration:
            base_fps = spec.get("fps", 8)
            max_frames = spec.get("max_frames", 32)
            num_frames = max(16, min(int(round(duration * base_fps)), max_frames))

        # ── Paramètres spécifiques AnimateLCM ─────────────────────────────────
        extra_kwargs = {}
        if spec.get("pipeline_class") == "AnimateDiffPipeline":
            # Résolution adaptative VRAM (l'attention est en O(N²)).
            # Avec sequential_cpu_offload (pas de débordement mémoire), benchmark
            # GTX 1650 4 Go : 256px ≈ 12 s/étape → vidéo en ~1-1,5 min.
            # Résolution : choix explicite de l'utilisateur (qualité) > auto-VRAM.
            if resolution in (256, 384, 512, 640, 768):
                w = h = resolution
            else:
                w = spec.get("width", 512)
                h = spec.get("height", 512)
                if dev.get("cuda"):
                    vg = dev["vram_gb"]
                    if vg <= 4:
                        w, h = 384, 384   # défaut équilibré (le sujet apparaît) ~3-4 min
                    elif vg <= 6:
                        w, h = 512, 512
            extra_kwargs["width"] = w
            extra_kwargs["height"] = h
            # Negative prompt : personnalisé si fourni, sinon défaut qualité
            extra_kwargs["negative_prompt"] = (negative_prompt.strip() if negative_prompt and negative_prompt.strip()
                else "bad quality, worse quality, low resolution, blurry, distorted, deformed, watermark, text")

            # Attention slicing UNIQUEMENT en haute résolution (>=384) sur petit GPU :
            # à 256px la matrice d'attention (~1 Go) tient sans découpage → le kernel
            # fusionné est PLUS rapide. À 384+, on découpe pour éviter l'OOM.
            if dev.get("cuda") and dev["vram_gb"] <= 6 and w >= 384:
                try:
                    from diffusers.models.attention_processor import SlicedAttnProcessor
                    pipe.unet.set_attn_processor(SlicedAttnProcessor(slice_size=16))
                except Exception:
                    pass
            else:
                # 256px (ou gros GPU) : processeur par défaut (fusionné, plus rapide)
                try:
                    from diffusers.models.attention_processor import AttnProcessor2_0
                    pipe.unet.set_attn_processor(AttnProcessor2_0())
                except Exception:
                    pass

            _put({
                "status": "processing", "progress": 5,
                "message": f"🎬 Génération {w}×{h} · {num_frames} frames · {num_steps} étapes…",
            })

        # ── Seed (reproductibilité / variations) ──────────────────────────────
        # seed >= 0 → résultat reproductible ; None/-1 → aléatoire (graine notée).
        # IMPORTANT : avec sequential/model cpu-offload, un generator sur un seul
        # device n'est pas appliqué de façon fiable aux latents (multi-device).
        # On fixe donc la graine GLOBALE (torch + cuda) ET on passe un generator :
        # c'est la méthode robuste pour rendre la composition reproductible.
        import random as _random
        if seed is None or seed < 0:
            used_seed = _random.randint(0, 2**31 - 1)
        else:
            used_seed = int(seed) % (2**31)
        try:
            torch.manual_seed(used_seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(used_seed)
            extra_kwargs["generator"] = torch.Generator(device="cpu").manual_seed(used_seed)
        except Exception:
            pass

        try:
            with torch.inference_mode():
                if spec["mode"] == "t2v":
                    result = pipe(
                        prompt=prompt,
                        num_frames=num_frames,
                        num_inference_steps=num_steps,
                        guidance_scale=guidance,
                        callback_on_step_end=_step_cb,
                        **extra_kwargs,
                    )
                else:  # i2v
                    from PIL import Image as _PIL
                    with _PIL.open(image_path) as img_raw:
                        img = img_raw.convert("RGB")
                    result = pipe(
                        prompt=prompt,
                        image=img,
                        num_frames=num_frames,
                        num_inference_steps=num_steps,
                        guidance_scale=guidance,
                        callback_on_step_end=_step_cb,
                        **extra_kwargs,
                    )

            # CRITICAL: synchronize before exporting to ensure all CUDA ops are done
            # This prevents "device not ready" errors during VAE decoding/export
            if torch.cuda.is_available():
                torch.cuda.synchronize()

        except RuntimeError as cuda_err:
            err_msg = str(cuda_err).lower()
            if "out of memory" in err_msg or "cuda" in err_msg:
                # Try to recover - clear memory and report user-friendly error
                _gc.collect()
                if torch.cuda.is_available():
                    try:
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()
                    except Exception:
                        pass
                # Also clear the cached pipeline so next attempt starts fresh
                _state["pipeline"] = None
                _state["model_key"] = None
                raise RuntimeError(
                    f"Erreur CUDA pendant la génération. "
                    f"Réduisez le nombre de frames (essayez 9-13 pour 4 Go VRAM) "
                    f"ou utilisez l'onglet 'Texte Animé' qui ne nécessite pas de GPU. "
                    f"Détails: {str(cuda_err)[:200]}"
                )
            raise

        # ── 6. Export MP4 ─────────────────────────────────────────────────────
        _put({"status": "processing", "progress": 97, "message": "💾 Export MP4…"})

        # Extract frames from result and move to CPU before video export
        # This decouples the GPU memory from the export step
        try:
            frames = result.frames[0]
            # If frames are torch tensors on GPU, move to CPU
            import torch as _torch
            if _torch.is_tensor(frames):
                frames = frames.cpu()
            # Free GPU memory now that frames are on CPU
            del result
            _gc.collect()
            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
        except Exception as frame_err:
            raise RuntimeError(f"Erreur extraction des frames : {frame_err}")

        from diffusers.utils import export_to_video
        out_filename = f"local_{uuid.uuid4()}.mp4"
        out_path     = str(_VIDEO_DIR / out_filename)
        n_out = len(frames) if hasattr(frames, "__len__") else num_frames
        try:
            # Export brut à la cadence native (fps du modèle)
            raw_path = str(_VIDEO_DIR / f"_raw_{out_filename}")
            export_to_video(frames, raw_path, fps=fps)
        except Exception as exp_err:
            raise RuntimeError(f"Erreur export MP4 : {exp_err}")

        # ── Durée réglable + lissage (interpolation de mouvement) ─────────────
        target_dur = duration if duration else (n_out / float(fps))
        retimed = False
        if duration or spec.get("pipeline_class") == "AnimateDiffPipeline":
            _put({"status": "processing", "progress": 98,
                  "message": f"🎞️ Mise à la durée ({target_dur:.1f}s) + lissage…"})
            retimed = _smooth_retime(raw_path, out_path, target_duration=target_dur,
                                     src_fps=fps, n_frames=n_out, target_fps=24)
        if retimed:
            # out_path contient la vidéo finale lissée ; on supprime le brut
            try: os.remove(raw_path)
            except Exception: pass
        else:
            # pas de retime (ou échec) → le brut DEVIENT la sortie finale
            try:
                os.replace(raw_path, out_path)
            except Exception:
                out_path = raw_path
                out_filename = os.path.basename(raw_path)

        file_size = os.path.getsize(out_path)
        _put({
            "status": "succeeded",
            "progress": 100,
            "filename": out_filename,
            "file_url": f"/api/video/files/{out_filename}",
            "size": file_size,
            "duration": round(target_dur, 1),
            "seed": used_seed,
        })

    except _GenAborted as ab:
        # Annulation propre (timeout ou bouton Annuler) — pas une vraie erreur
        _put({"status": "cancelled", "message": str(ab)})
        # Le pipeline peut être dans un état instable après abort → on le décharge
        try:
            _state["pipeline"] = None
            _state["model_key"] = None
            import torch as _torch, gc as _gc2
            _gc2.collect()
            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
        except Exception:
            pass
    except Exception as exc:
        import traceback
        _put({
            "status": "error",
            "error": str(exc),
            "detail": traceback.format_exc()[-1500:],
        })
        # Attempt to recover GPU state for next try
        try:
            import torch as _torch, gc as _gc2
            _gc2.collect()
            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
                _torch.cuda.synchronize()
        except Exception:
            pass
    finally:
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)  # sentinel


# ── Générateur SSE asynchrone ─────────────────────────────────────────────────

async def generate_video_local_sse(
    model_key: str,
    prompt: str,
    num_steps: int | None = None,
    num_frames: int | None = None,
    fps: int | None = None,
    guidance: float | None = None,
    image_path: str | None = None,
    duration: float | None = None,
    resolution: int | None = None,
    seed: int | None = None,
    negative_prompt: str | None = None,
):
    """
    Générateur asynchrone SSE.
    Yield des chaînes 'data: {...}\\n\\n' jusqu'à la fin.
    """
    spec = LOCAL_MODELS.get(model_key)
    if not spec:
        yield f"data: {json.dumps({'status': 'error', 'error': f'Modèle inconnu : {model_key}'})}\n\n"
        return

    steps    = num_steps  if num_steps  is not None else spec["steps"]
    # Si une durée est demandée (AnimateLCM), on laisse _run_generation calculer
    # le nb de frames depuis la durée ; sinon on prend la valeur fournie/défaut.
    frames   = num_frames if num_frames is not None else spec["frames"]
    fps_val  = fps        if fps        is not None else spec["fps"]
    guid_val = guidance   if guidance   is not None else spec["guidance"]

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    loop.run_in_executor(
        _executor,
        _run_generation,
        model_key, prompt, steps, frames, fps_val, guid_val,
        image_path, queue, loop, duration, resolution, seed, negative_prompt,
    )

    while True:
        try:
            # Timeout 25s → envoie un commentaire SSE keepalive si rien ne vient
            # (évite la fermeture de connexion pendant le long téléchargement du modèle)
            item = await asyncio.wait_for(queue.get(), timeout=25)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"  # commentaire SSE, n'active pas onmessage côté client
            continue
        if item is None:
            break
        yield f"data: {json.dumps(item)}\n\n"
        if item.get("status") in ("succeeded", "error", "cancelled"):
            break
