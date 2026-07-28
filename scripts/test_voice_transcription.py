"""Tests contractuels du service Whisper partagé, sans modèle ni réseau."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(ROOT)

import voice_transcription


class FakeModel:
    def __init__(self, name: str) -> None:
        self.name = name

    def transcribe(self, _path: str, **kwargs):
        language = kwargs.get("language") or "fr"
        return [SimpleNamespace(text=f" texte {self.name} ")], SimpleNamespace(language=language)


async def main() -> None:
    loaded: list[str] = []

    def loader(name: str):
        loaded.append(name)
        if name == "medium":
            raise RuntimeError("modèle absent")
        return FakeModel(name)

    voice_transcription.reset_cache()
    voice_transcription.configure(model_provider=lambda: "small", loader=loader)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        audio = root / "sample.wav"
        audio.write_bytes(b"\0" * 2048)

        first = await voice_transcription.transcribe_file(audio, language="fr")
        second = await voice_transcription.transcribe_file(audio, language="auto")
        assert first["success"] and first["model_used"] == "small"
        assert second["success"] and loaded.count("small") == 1

        fallback = await voice_transcription.transcribe_file(audio, model_name="medium")
        assert fallback["success"] and fallback["model_used"] == "base"
        assert "fallback_reason" in fallback

        tiny = await voice_transcription.transcribe_file(audio, model_name="tiny")
        assert tiny["success"]
        assert len(voice_transcription._models) == voice_transcription.MAX_CACHED_MODELS
        assert "small" not in voice_transcription._models

        assert not (await voice_transcription.transcribe_file(audio, model_name="invalid"))["success"]
        assert not (await voice_transcription.transcribe_file(audio, language="français"))["success"]
        invalid = root / "sample.exe"
        invalid.write_bytes(b"\0" * 2048)
        assert not (await voice_transcription.transcribe_file(invalid))["success"]

        import tools

        facade = await tools.execute_voice_transcribe(
            {"audio_path": str(audio), "model": "base", "language": "fr"}
        )
        assert facade["success"] and facade["model_used"] == "base"

        from api import voice

        assert voice.prewarm_whisper is voice_transcription.prewarm
        original_transcribe = voice_transcription.transcribe_file
        captured_path: list[str] = []

        async def fake_transcribe(path, **_kwargs):
            captured_path.append(str(path))
            assert Path(path).stat().st_size == 2048
            return {"success": True, "text": "api", "language": "fr"}

        voice_transcription.transcribe_file = fake_transcribe
        try:
            from starlette.datastructures import UploadFile

            upload = UploadFile(
                filename="sample.wav",
                file=BytesIO(b"\0" * 2048),
                headers={"content-type": "audio/wav"},
            )
            api_result = await voice.voice_transcribe(upload, "fr")
            assert api_result["success"] and api_result["text"] == "api"
            assert captured_path and not Path(captured_path[0]).exists()
        finally:
            voice_transcription.transcribe_file = original_transcribe

    voice_transcription.reset_cache()
    voice_transcription.configure(
        model_provider=lambda: os.getenv("WHISPER_MODEL", "small"),
        loader=voice_transcription._default_loader,
    )
    print("PASS: transcription Whisper partagee, bornee et observable")


if __name__ == "__main__":
    asyncio.run(main())
