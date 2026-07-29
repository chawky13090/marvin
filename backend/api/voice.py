"""Transcription Whisper locale et synthèse vocale Edge-TTS."""

import asyncio
import os
import re
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import database as db
import api_errors
import voice_transcription


router = APIRouter(tags=["voice"])


def _whisper_model_size() -> str:
    try:
        setting = db.get_setting("whisper_model")
        if setting and str(setting).strip():
            return str(setting).strip()
    except Exception:
        pass
    return os.getenv("WHISPER_MODEL", "small")


voice_transcription.configure(model_provider=_whisper_model_size)
prewarm_whisper = voice_transcription.prewarm


@router.post("/api/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...), language: str = Form("fr")):
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
    bytes_written = 0
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temporary:
            temporary_path = temporary.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > voice_transcription.MAX_AUDIO_BYTES:
                    raise HTTPException(status_code=413, detail="Fichier audio supérieur à 512 Mio")
                temporary.write(chunk)

        result = await voice_transcription.transcribe_file(temporary_path, language=language)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Transcription échouée"))
        return result
    except HTTPException:
        raise
    except Exception as error:
        raise api_errors.internal_http_error(
            "voice_transcription", error, "Transcription impossible."
        ) from error
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


async def _synthesize_edge_audio(edge_tts_module, text: str, voice_id: str, rate: str, pitch: str) -> bytes:
    """Effectue une unique relance bornée sur les pannes transitoires Edge-TTS."""
    last_error = None
    for attempt in range(2):
        try:
            communication = edge_tts_module.Communicate(text, voice_id, rate=rate, pitch=pitch)
            chunks = []
            async for chunk in communication.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
            audio = b"".join(chunks)
            if audio:
                return audio
            last_error = RuntimeError("NoAudioReceived")
        except Exception as error:
            last_error = error
        if attempt == 0:
            await asyncio.sleep(0.2)
    raise last_error or RuntimeError("NoAudioReceived")


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

        audio = await _synthesize_edge_audio(
            edge_tts,
            text,
            voice_id,
            request.rate,
            request.pitch,
        )
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
        raise api_errors.internal_http_error(
            "voice_tts", error, "Synthèse vocale impossible."
        ) from error
