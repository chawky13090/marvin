"""Deterministic tests for bounded, idempotent local model downloads."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import local_model_installer


class FakeResponse:
    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        yield json.dumps({"status": "pulling manifest"})
        yield json.dumps({"status": "downloading", "total": 100, "completed": 40})
        yield json.dumps({"status": "success", "total": 100, "completed": 100})


class FakeStream:
    async def __aenter__(self):
        return FakeResponse()

    async def __aexit__(self, *_args):
        return False


class FakeClient:
    def stream(self, method, url, json):
        assert method == "POST"
        assert url.endswith("/api/pull")
        assert json == {"model": "qwen3:4b", "stream": True}
        return FakeStream()


async def scenario() -> None:
    settings = {}
    with (
        patch.object(local_model_installer.db, "get_setting", side_effect=lambda key: settings.get(key)),
        patch.object(local_model_installer.db, "set_setting", side_effect=lambda key, value: settings.__setitem__(key, value)),
    ):
        state = {"status": "running", "models": ["qwen3:4b"], "installed": [], "failed": []}
        await local_model_installer._pull_one(FakeClient(), "qwen3:4b", state)
        assert state["completed_bytes"] == 100
        assert settings["local_model_download_status"]["phase"] == "success"

        confirmation = local_model_installer.start(["qwen3:4b"], confirmed=False)
        assert confirmation["requiresConfirmation"] is True
        try:
            local_model_installer.start(["unknown:99b"], confirmed=True)
        except ValueError:
            pass
        else:
            raise AssertionError("Un modèle hors catalogue devait être refusé.")

        gate = asyncio.Event()

        async def pending(_models):
            await gate.wait()

        with patch.object(local_model_installer, "_run", side_effect=pending):
            started = local_model_installer.start(["qwen3:4b"], confirmed=True)
            duplicate = local_model_installer.start(["qwen3:4b"], confirmed=True)
            assert started["status"] == "queued"
            assert duplicate["status"] == "already_running"
            gate.set()
            await local_model_installer._TASK
        await local_model_installer.shutdown()


def main() -> int:
    asyncio.run(scenario())
    print("Local Model Installer OK - confirmation, allowlist, progression et idempotence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
