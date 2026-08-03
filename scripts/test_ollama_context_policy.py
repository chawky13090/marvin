"""Tests déterministes du calcul de contexte matériel Ollama."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import ollama_context_policy as policy
import auto_config


def _show(*, layers: int = 36, kv_heads: int = 8, width: int = 128) -> dict:
    return {
        "model_info": {
            "qwen3.block_count": layers,
            "qwen3.attention.head_count_kv": kv_heads,
            "qwen3.attention.key_length": width,
            "qwen3.attention.value_length": width,
            "qwen3.context_length": 262_144,
        }
    }


def main() -> int:
    assert auto_config.context_objective_tokens({"vendor": "cpu", "vram_gb": 0}) == 8_192
    assert auto_config.context_objective_tokens({"vendor": "nvidia", "vram_gb": 4}) == 32_768
    assert auto_config.context_objective_tokens({"vendor": "nvidia", "vram_gb": 12}) == 65_536
    assert auto_config.context_objective_tokens({"vendor": "nvidia", "vram_gb": 24}) == 131_072
    shape = policy.extract_attention_shape(_show())
    assert shape["status"] == "calculated"
    assert policy.kv_cache_bytes(shape, 32_768, cache_type="f16") == 4_831_838_208
    assert policy.kv_cache_bytes(shape, 32_768, cache_type="q8_0") == 2_415_919_104

    result = policy.propose_context_candidates(
        _show(),
        model_size_bytes=2_500_000_000,
        vram_budget_bytes=3 * policy.GIB,
        ram_available_bytes=20 * policy.GIB,
    )
    assert result["runtime_verification_required"] is True
    assert len(result["candidates"]) <= 2
    assert any(
        item["context_tokens"] == 32_768 and item["kv_cache_type"] == "q8_0"
        for item in result["candidates"]
    )

    hybrid = _show()
    hybrid["model_info"]["qwen3.attention.sliding_window_pattern"] = 4
    assert policy.extract_attention_shape(hybrid)["status"] == "estimated"

    try:
        policy.extract_attention_shape({"model_info": {"x.context_length": 8192}})
    except policy.ContextPolicyError as exc:
        assert str(exc) == "attention_shape_incomplete"
    else:
        raise AssertionError("Une forme incomplète doit être refusée.")

    print("Ollama context policy OK - calcul KV, candidats bornés et hybrides signalés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
