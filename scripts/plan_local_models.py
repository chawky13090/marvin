"""Produit le plan local adapté à la machine pour l'installateur Windows."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import local_model_policy  # noqa: E402


def installed_models(ollama_url: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/tags",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return []
    return [
        {
            "name": str(item.get("name") or ""),
            "size_bytes": int(item.get("size") or 0),
        }
        for item in payload.get("models", [])
        if isinstance(item, dict)
    ]


def build_plan(hardware: dict[str, Any], installed: list[dict[str, Any]]) -> list[str]:
    recommendation = local_model_policy.recommend(hardware, installed)
    return [
        str(item["model"])
        for item in recommendation["downloads"]
        if item.get("disk_ready") is True
    ]


def main() -> int:
    import auto_config

    ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    for model in build_plan(auto_config.detect_hardware(), installed_models(ollama_url)):
        print(model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
