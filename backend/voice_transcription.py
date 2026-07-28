"""Service partagé de transcription locale Whisper."""

from __future__ import annotations

import asyncio
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable


SUPPORTED_MODELS = frozenset({"tiny", "base", "small", "medium", "large-v3"})
SUPPORTED_EXTENSIONS = frozenset({".wav", ".webm", ".ogg", ".mp3", ".mpeg", ".mp4", ".m4a", ".flac"})
MAX_AUDIO_BYTES = 512 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 500_000
MAX_CACHED_MODELS = 2

_model_provider: Callable[[], str] = lambda: os.getenv("WHISPER_MODEL", "small")
_loader: Callable[[str], Any] | None = None
_models: OrderedDict[str, Any] = OrderedDict()
_load_lock = asyncio.Lock()
_model_locks: dict[str, asyncio.Lock] = {}


def _default_loader(model_name: str) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "faster-whisper non installé. Installez les dépendances backend."
        ) from error
    return WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=min(8, os.cpu_count() or 4),
        num_workers=1,
    )


def configure(
    *,
    model_provider: Callable[[], str] | None = None,
    loader: Callable[[str], Any] | None = None,
) -> None:
    """Injecte la configuration sans dupliquer le cache entre API et outils."""
    global _model_provider, _loader
    if model_provider is not None:
        _model_provider = model_provider
    if loader is not None:
        _loader = loader


def reset_cache() -> None:
    """Vide le cache. Utile au rollback de configuration et dans les tests."""
    _models.clear()
    _model_locks.clear()


def _normalise_model(model_name: str | None) -> str:
    candidate = str(model_name or _model_provider() or "small").strip().lower()
    if candidate not in SUPPORTED_MODELS:
        raise ValueError(
            f"Modèle Whisper non supporté : {candidate}. "
            f"Valeurs : {', '.join(sorted(SUPPORTED_MODELS))}"
        )
    return candidate


def _normalise_language(language: str | None) -> str | None:
    candidate = str(language or "").strip().lower()
    if candidate in {"", "auto", "detect"}:
        return None
    if not re.fullmatch(r"[a-z]{2,3}", candidate):
        raise ValueError("Langue invalide : code ISO 639 attendu, ou 'auto'.")
    return candidate


async def _load_model(requested: str) -> tuple[Any, str, str | None]:
    async with _load_lock:
        if requested in _models:
            model = _models.pop(requested)
            _models[requested] = model
            return model, requested, None

        loader = _loader or _default_loader
        loaded_name = requested
        fallback_reason = None
        try:
            model = await asyncio.to_thread(loader, requested)
        except Exception as first_error:
            if requested == "base":
                raise
            loaded_name = "base"
            fallback_reason = f"{requested} indisponible : {first_error}"
            if loaded_name in _models:
                model = _models.pop(loaded_name)
            else:
                model = await asyncio.to_thread(loader, loaded_name)

        _models[loaded_name] = model
        _model_locks.setdefault(loaded_name, asyncio.Lock())
        while len(_models) > MAX_CACHED_MODELS:
            evicted_name, _ = _models.popitem(last=False)
            _model_locks.pop(evicted_name, None)
        return model, loaded_name, fallback_reason


async def transcribe_file(
    audio_path: str | os.PathLike[str],
    *,
    model_name: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    path = Path(audio_path).resolve()
    if not path.is_file():
        return {"success": False, "error": f"Fichier audio introuvable : {path}"}
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return {"success": False, "error": f"Format audio non supporté : {path.suffix or '(absent)'}"}
    size = path.stat().st_size
    if size < 1000:
        return {"success": False, "error": "Fichier audio trop court ou vide"}
    if size > MAX_AUDIO_BYTES:
        return {"success": False, "error": "Fichier audio supérieur à la limite de 512 Mio"}

    try:
        requested_model = _normalise_model(model_name)
        requested_language = _normalise_language(language)
        model, used_model, fallback_reason = await _load_model(requested_model)
        model_lock = _model_locks.setdefault(used_model, asyncio.Lock())

        def run() -> tuple[str, str | None]:
            prompt = (
                "Transcription en français, avec les accents et la ponctuation. "
                "L'utilisateur parle à son assistant Marvin."
                if requested_language in (None, "fr")
                else None
            )
            segments, info = model.transcribe(
                str(path),
                beam_size=5,
                best_of=5,
                language=requested_language,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=prompt,
                no_speech_threshold=0.6,
                temperature=0.0,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return text[:MAX_TRANSCRIPT_CHARS], getattr(info, "language", requested_language)

        async with model_lock:
            text, detected_language = await asyncio.to_thread(run)
        result: dict[str, Any] = {
            "success": True,
            "audio_file": str(path),
            "text": text,
            "language": detected_language,
            "char_count": len(text),
            "model_requested": requested_model,
            "model_used": used_model,
            "local_only": True,
        }
        if fallback_reason:
            result["fallback_reason"] = fallback_reason
        if not text:
            result["warning"] = "Aucune parole détectée."
        return result
    except (ValueError, RuntimeError) as error:
        return {"success": False, "error": str(error), "audio_file": str(path)}
    except Exception as error:
        return {
            "success": False,
            "error": f"Transcription échouée : {error}",
            "audio_file": str(path),
        }


async def prewarm() -> None:
    """Charge le modèle configuré sans masquer un échec au superviseur appelant."""
    await _load_model(_normalise_model(None))
