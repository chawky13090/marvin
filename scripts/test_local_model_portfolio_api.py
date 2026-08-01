"""Contrats API de la politique autonome des modèles locaux."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import runtime_config
import auto_config
import local_model_installer
import local_model_portfolio


MODELS = [{
    "name": "qwen3.5:2b",
    "size_bytes": 2_700_000_000,
    "capabilities": ["completion", "vision", "tools", "thinking"],
    "context_tokens": 262144,
}]
HARDWARE = {
    "vendor": "nvidia", "vram_gb": 4.0, "ram_gb": 32,
    "ram_available_gb": 16, "disk_free_bytes": 50 * 1024 ** 3,
}


async def scenario() -> None:
    settings = {}
    with (
        patch.object(runtime_config.db, "get_setting", side_effect=settings.get),
        patch.object(runtime_config.db, "set_setting", side_effect=settings.__setitem__),
        patch.object(auto_config, "_installed_models", new=AsyncMock(return_value=MODELS)),
        patch.object(auto_config, "detect_hardware", return_value=HARDWARE),
        patch.object(local_model_portfolio, "network_cost", return_value="unmetered"),
        patch.object(local_model_installer, "start", return_value={"status": "queued"}) as start,
        patch.object(runtime_config.audit, "log_action") as audit_log,
    ):
        body = runtime_config.LocalPortfolioPolicyBody(
            enabled=True,
            auto_download=True,
            download_network="unmetered",
            max_disk_gb=25,
            min_free_disk_gb=10,
            maintained_roles=["chat", "agent", "analysis", "vision", "coding", "ocr", "embedding"],
        )
        result = await runtime_config.update_local_model_policy(body)
        assert result["policy"]["auto_download"] is True
        assert result["deletion_planned"] is False
        assert "qwen2.5-coder:3b" in result["auto_download_queue"]
        start.assert_called_once()
        audit_log.assert_called_once()

        status = await runtime_config.local_model_policy_status()
        assert status["policy"]["delete_requires_confirmation"] is True


def main() -> int:
    asyncio.run(scenario())
    print("Local Model Portfolio API OK - persistance, file contrôlée et audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
