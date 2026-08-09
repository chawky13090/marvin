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
            "qwen3.attention.head_count": 32,
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

    derived = {
        "model_info": {
            "qwen2.block_count": 36,
            "qwen2.context_length": 32_768,
            "qwen2.embedding_length": 2_048,
            "qwen2.attention.head_count": 16,
            "qwen2.attention.head_count_kv": 2,
        }
    }
    derived_shape = policy.extract_attention_shape(derived)
    assert derived_shape["key_length"] == 128
    assert "key_length_from_embedding_length_div_head_count" in derived_shape["derivations"]

    multimodal = {
        "model_info": {
            "qwen35.block_count": 24,
            "qwen35.context_length": 262_144,
            "qwen35.embedding_length": 2_048,
            "qwen35.attention.head_count": 8,
            "qwen35.attention.head_count_kv": None,
            "qwen35.attention.key_length": 256,
            "qwen35.attention.value_length": 256,
            "qwen35.full_attention_interval": 4,
            "qwen35.vision.block_count": 96,
            "qwen35.vision.embedding_length": 8_192,
            "qwen35.vision.attention.head_count": 64,
        }
    }
    multimodal_shape = policy.extract_attention_shape(multimodal)
    assert multimodal_shape["metadata_namespace"] == "qwen35"
    assert multimodal_shape["layer_count"] == 24
    assert multimodal_shape["attention_layer_count"] == 6
    assert multimodal_shape["kv_head_count"] == 8
    assert "kv_head_count_from_attention_head_count_upper_bound" in multimodal_shape["derivations"]

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
