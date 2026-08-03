"""Résout le profil Ollama vérifié pour le lanceur Windows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PROFILE = ROOT / "data" / "install" / "ollama-context-profile.json"
sys.path.insert(0, str(BACKEND))

import auto_config  # noqa: E402
import ollama_context_policy as context_policy  # noqa: E402


def _fingerprint(hardware: dict) -> dict:
    return {
        "vendor": str(hardware.get("vendor") or "unknown"),
        "gpu": str(hardware.get("gpu") or "unknown"),
        "vram_gb": round(float(hardware.get("vram_gb") or 0), 1),
        "ram_gb": round(float(hardware.get("ram_gb") or 0), 1),
    }


def resolve(path: Path = PROFILE) -> dict:
    bootstrap = {
        "status": "bootstrap_unverified",
        "context_tokens": 8192,
        "kv_cache_type": "f16",
        "flash_attention": 1,
        "parallel": 1,
        "reason": "verified_profile_missing",
    }
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return bootstrap
    machine = _fingerprint(auto_config.detect_hardware())
    if (
        profile.get("schema") != "marvin.ollama-context-profile/1.0"
        or profile.get("status") != "verified"
        or profile.get("machine_key") != context_policy.machine_profile_key(machine)
        or not isinstance(profile.get("selected"), dict)
    ):
        return {**bootstrap, "reason": "verified_profile_invalid_or_for_another_machine"}
    selected = profile["selected"]
    context = int(selected.get("context_tokens") or 0)
    cache_type = str(selected.get("kv_cache_type") or "")
    if context < 8192 or context > 1_048_576 or cache_type not in {"f16", "q8_0"}:
        return {**bootstrap, "reason": "verified_profile_values_invalid"}
    return {
        "status": "verified",
        "context_tokens": context,
        "kv_cache_type": cache_type,
        "flash_attention": 1,
        "parallel": 1,
        "reason": "machine_bound_runtime_verification",
        "model": str(profile.get("model") or ""),
        "model_digest": str(profile.get("model_digest") or ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "cmd"), default="json")
    args = parser.parse_args()
    result = resolve()
    if args.format == "cmd":
        print(f"OLLAMA_CONTEXT_LENGTH={result['context_tokens']}")
        print(f"OLLAMA_KV_CACHE_TYPE={result['kv_cache_type']}")
        print(f"OLLAMA_FLASH_ATTENTION={result['flash_attention']}")
        print(f"OLLAMA_NUM_PARALLEL={result['parallel']}")
        print(f"MARVIN_OLLAMA_PROFILE_STATUS={result['status']}")
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
