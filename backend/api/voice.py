"""Transcription Whisper locale et synthèse vocale Edge-TTS."""

import asyncio
import os
import re
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import database as db


router = APIRouter(tags=["voice"])
_whisper_model = None
_whisper_lock = asyncio.Lock()


def _whisper_model_size() -> str:
    try:
        setting = db.get_setting("whisper_model")
        if setting and str(setting).strip():
            return str(setting).strip()
    except Exception:
        pass
    return os.getenv("WHISPER_MODEL", "small")


async def _get_whisper():
    global _whisper_model
    async with _whisper_lock:
        if _whisper_model is None:
            def load():
                from faster_whisper import WhisperModel

                threads = min(8, os.cpu_count() or 4)
                try:
                    return WhisperModel(
                        _whisper_model_size(),
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=threads,
                        num_workers=1,
                    )
                except Exception:
                    return WhisperModel(
                        "base",
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=threads,
                        num_workers=1,
                    )

            _whisper_model = await asyncio.get_running_loop().run_in_executor(None, load)
    return _whisper_model


async def prewarm_whisper():
    try:
        await asyncio.sleep(2)
        await _get_whisper()
    except Exception:
        pass


@router.post("/api/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...), language: str = Form("fr")):
    audio_bytes = await file.read()
    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=400, detail="Fichier audio trop court ou vide")

    extension = ".webm"
    if file.content_type:
        content_type = file.content_type.lower()
        if "wav" in content_type:
            extension = ".wav"
        elif "ogg" in content_type:
            extension = ".ogg"
        elif "mp3" in content_type or "mpeg" in content_type:
            extension = ".mp3"
        elif "mp4" in content_type:
            extension = ".mp4"
    elif file.filename:
        detected = os.path.splitext(file.filename)[1]
        if detected:
            extension = detected

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temporary:
            temporary.write(audio_bytes)
            temporary_path = temporary.name

        model = await _get_whisper()
        requested_language = (language or "fr").strip().lower()
        language_argument = None if requested_language in ("auto", "", "detect") else requested_language
        french_prompt = (
            "Transcription en français, avec les accents et la ponctuation. "
            "L'utilisateur parle à son assistant Marvin."
        )

        def transcribe():
            segments, info = model.transcribe(
                temporary_path,
                beam_size=5,
                best_of=5,
                language=language_argument,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=french_prompt if language_argument in (None, "fr") else None,
                no_speech_threshold=0.6,
                temperature=0.0,
            )
            return " ".join(segment.text.strip() for segment in segments).strip(), info.language

        text, detected_language = await asyncio.get_running_loop().run_in_executor(None, transcribe)
        return {"success": True, "text": text, "language": detected_language}
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Transcription échouée : {error}")
    finally:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except Exception:
                pass


DEFAULT_TTS_VOICES = {
    "henri": {"id": "fr-FR-HenriNeural", "gender": "Male", "label": "Henri (homme, voix professionnelle)"},
    "denise": {"id": "fr-FR-DeniseNeural", "gender": "Female", "label": "Denise (femme, voix naturelle)"},
    "eloise": {"id": "fr-FR-EloiseNeural", "gender": "Female", "label": "Eloïse (femme, voix douce)"},
    "vivienne": {"id": "fr-FR-VivienneMultilingualNeural", "gender": "Female", "label": "Vivienne (multilingue)"},
    "remy": {"id": "fr-FR-RemyMultilingualNeural", "gender": "Male", "label": "Rémy (multilingue)"},
    "thierry": {"id": "fr-CA-ThierryNeural", "gender": "Male", "label": "Thierry (Québec)"},
    "sylvie": {"id": "fr-CA-SylvieNeural", "gender": "Female", "label": "Sylvie (Québec)"},
}


class TTSRequest(BaseModel):
    text: str
    voice: str = "henri"
    rate: str = "+0%"
    pitch: str = "+0Hz"


@router.get("/api/voice/voices")
async def voice_list_voices():
    return {
        "voices": [{"key": key, **voice} for key, voice in DEFAULT_TTS_VOICES.items()],
        "default": "henri",
    }


@router.post("/api/voice/speak")
async def voice_speak(request: TTSRequest):
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Texte requis")
    voice_id = request.voice
    if voice_id in DEFAULT_TTS_VOICES:
        voice_id = DEFAULT_TTS_VOICES[voice_id]["id"]
    elif not voice_id.startswith(("fr-", "en-", "es-", "de-", "it-")):
        voice_id = DEFAULT_TTS_VOICES["henri"]["id"]

    text = request.text.strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    if len(text) > 3000:
        text = text[:3000] + "…"

    try:
        import edge_tts

        communication = edge_tts.Communicate(
            text,
            voice_id,
            rate=request.rate,
            pitch=request.pitch,
        )
        chunks = []
        async for chunk in communication.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        audio = b"".join(chunks)
        if not audio:
            raise HTTPException(status_code=500, detail="Aucun audio généré")
        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=marvin_voice.mp3",
                "Cache-Control": "no-cache",
                "X-Voice-Used": voice_id,
                "X-Audio-Size": str(len(audio)),
            },
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="edge-tts non installé. pip install edge-tts")
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"TTS error: {str(error)[:200]}")
