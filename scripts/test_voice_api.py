"""Régressions déterministes de la synthèse Edge-TTS."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api.voice import _synthesize_edge_audio


class FakeCommunication:
    attempts = 0

    def __init__(self, *_args, **_kwargs):
        type(self).attempts += 1
        self.attempt = type(self).attempts

    async def stream(self):
        if self.attempt == 1:
            raise RuntimeError("NoAudioReceived")
        yield {"type": "audio", "data": b"valid-mp3"}


class AlwaysEmptyCommunication:
    attempts = 0

    def __init__(self, *_args, **_kwargs):
        type(self).attempts += 1

    async def stream(self):
        if False:
            yield None


class Module:
    Communicate = FakeCommunication


class EmptyModule:
    Communicate = AlwaysEmptyCommunication


async def main():
    audio = await _synthesize_edge_audio(Module, "Bonjour", "fr-FR-HenriNeural", "+0%", "+0Hz")
    assert audio == b"valid-mp3"
    assert FakeCommunication.attempts == 2

    try:
        await _synthesize_edge_audio(EmptyModule, "Bonjour", "fr-FR-HenriNeural", "+0%", "+0Hz")
        raise AssertionError("Une synthèse vide doit échouer")
    except RuntimeError as error:
        assert str(error) == "NoAudioReceived"
    assert AlwaysEmptyCommunication.attempts == 2

    print("Voice API OK - retry borne, audio valide et echec final explicite.")


if __name__ == "__main__":
    asyncio.run(main())
