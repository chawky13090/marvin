"""
Marvin — génération d'image locale (logos, icônes) via un modèle de diffusion léger.

v2.183 — né d'un vrai échec observé en conversation : demandé un logo, Marvin n'avait
AUCUN outil de génération d'image et a tenté de le dessiner à la main via PowerShell
(System.Drawing) — 7 tentatives consécutives échouées (voir le bug du double-emballage
PowerShell corrigé dans tools.py la même session). Marvin dispose déjà de `diffusers` +
`torch` CUDA pour la génération vidéo locale (local_video.py) — même stack, même GPU,
juste jamais branché sur un pipeline TEXTE→IMAGE. Réutilise `local_video.get_device_info`/
`_optimal_dtype` (même détection GPU dynamique, même choix de précision).

Modèle : `stabilityai/sd-turbo` — distillé à 1 seule étape d'inférence (pas de CFG,
guidance_scale=0.0), ~2 Go, rapide même sur un GPU modeste (quelques secondes sur une
RTX 2060). Choisi spécifiquement pour des LOGOS/ICÔNES (usage court, itératif) plutôt
qu'un modèle SDXL complet (plus lourd, plus lent, overkill pour ce cas d'usage).
"""
import os
import time
import uuid
from pathlib import Path

import local_video as _lv

_pipe_cache = {"pipe": None, "device": None}

_LOGO_MODEL_ID = "stabilityai/sd-turbo"

# Habillage de prompt : pousse vers un rendu "logo" (aplat, simple, centré, fond uni)
# plutôt qu'une image photo-réaliste générique — sans ça, sd-turbo produit souvent des
# scènes complexes peu utilisables comme logo d'en-tête de document.
_LOGO_PROMPT_TEMPLATE = (
    "simple flat vector logo icon, {prompt}, minimalist, centered composition, "
    "solid plain background, clean lines, professional corporate branding, high contrast, "
    "no text, no watermark"
)


def is_available() -> dict:
    """Vérifie si la génération d'image locale est utilisable sur cette machine —
    ne charge PAS le modèle (juste torch + diffusers importables, sans coût GPU)."""
    try:
        import torch  # noqa: F401
        import diffusers  # noqa: F401
    except Exception as e:
        return {"ok": False, "reason": f"Dépendance manquante ({e}). "
                "Installez : pip install -r backend/requirements-video.txt"}
    dev = _lv.get_device_info()
    return {"ok": True, "device": dev.get("device_name"), "cuda": dev.get("cuda")}


def _get_pipeline():
    dev = _lv.get_device_info()
    device_key = f"{dev.get('backend')}:{dev.get('device_name')}"
    if _pipe_cache["pipe"] is not None and _pipe_cache["device"] == device_key:
        return _pipe_cache["pipe"], dev

    import torch
    from diffusers import AutoPipelineForText2Image

    dtype = _lv._optimal_dtype(dev)
    pipe = AutoPipelineForText2Image.from_pretrained(
        _LOGO_MODEL_ID, torch_dtype=dtype, safety_checker=None,
    )
    if dev.get("cuda"):
        pipe = pipe.to("cuda")
    else:
        pipe = pipe.to("cpu")

    _pipe_cache["pipe"] = pipe
    _pipe_cache["device"] = device_key
    return pipe, dev


def generate_logo_image(prompt: str, out_path: str, size: int = 512, seed: int | None = None) -> dict:
    """Génère une image (bloquant — appeler via asyncio.to_thread) et l'enregistre en PNG.
    Retourne {success, path, generation_seconds} ou {success: False, error}."""
    avail = is_available()
    if not avail["ok"]:
        return {"success": False, "error": avail["reason"]}

    t0 = time.monotonic()
    try:
        pipe, dev = _get_pipeline()
        import torch
        generator = None
        if seed is not None:
            generator = torch.Generator(device="cuda" if dev.get("cuda") else "cpu").manual_seed(seed)

        full_prompt = _LOGO_PROMPT_TEMPLATE.format(prompt=prompt)
        result = pipe(
            prompt=full_prompt,
            num_inference_steps=1,      # sd-turbo est distillé pour 1 étape
            guidance_scale=0.0,         # pas de classifier-free guidance sur ce modèle
            width=size, height=size,
            generator=generator,
        )
        image = result.images[0]

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        image.save(out)

        return {
            "success": True,
            "path": str(out),
            "generation_seconds": round(time.monotonic() - t0, 1),
            "device": dev.get("device_name"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
