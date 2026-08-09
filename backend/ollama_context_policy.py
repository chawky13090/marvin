"""Politique matérielle reproductible pour le contexte des modèles Ollama locaux.

Le contexte n'est jamais déduit de la seule VRAM. Le coût du cache KV dépend du
modèle, du type de cache et du parallélisme. Ce module calcule des candidats puis
exige une observation ``/api/ps`` avant de qualifier une allocation de vérifiée.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


GIB = 1024**3
MIB = 1024**2
CONTEXT_CANDIDATES = (8_192, 16_384, 32_768, 65_536, 131_072)
KV_BYTES_PER_ELEMENT = {"f16": 2.0, "q8_0": 1.0, "q4_0": 0.5}


class ContextPolicyError(ValueError):
    """Métadonnées insuffisantes ou incohérentes pour une estimation sûre."""


def _numeric_metadata(model_info: dict[str, Any], suffix: str) -> float | None:
    values = [
        float(value)
        for key, value in model_info.items()
        if str(key).endswith(suffix)
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) > 0
    ]
    return max(values) if values else None


_NON_TEXT_NAMESPACES = (".vision.", ".audio.", ".image.", ".mmproj.", ".projector.")


def _positive_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0:
        return float(value)
    return None


def _text_namespace(model_info: dict[str, Any]) -> str:
    """Retourne l'unique espace de métadonnées du transformeur texte.

    Les modèles multimodaux publient aussi ``*.vision.*`` ou ``*.audio.*``.
    Une recherche globale par suffixe peut alors combiner deux architectures et
    produire un budget KV faux. Une ambiguïté résiduelle échoue fermée.
    """

    candidates: set[str] = set()
    for key, value in model_info.items():
        normalized = str(key).casefold()
        if any(marker in normalized for marker in _NON_TEXT_NAMESPACES):
            continue
        if normalized.endswith(".context_length") and _positive_number(value):
            candidates.add(str(key)[: -len(".context_length")])
    if not candidates:
        for key, value in model_info.items():
            normalized = str(key).casefold()
            if any(marker in normalized for marker in _NON_TEXT_NAMESPACES):
                continue
            if normalized.endswith(".block_count") and _positive_number(value):
                candidates.add(str(key)[: -len(".block_count")])
    if len(candidates) != 1:
        raise ContextPolicyError("text_namespace_ambiguous")
    return next(iter(candidates))


def _namespace_number(
    model_info: dict[str, Any], namespace: str, field: str
) -> float | None:
    return _positive_number(model_info.get(f"{namespace}.{field}"))


def extract_attention_shape(show_payload: dict[str, Any]) -> dict[str, Any]:
    """Extrait une forme KV standard et signale les architectures non prouvées.

    La formule couvre les transformers dont toutes les couches utilisent la même
    attention. Les architectures hybrides ou sans métadonnées explicites restent
    ``unsupported`` : Marvin ne fabrique alors pas une précision trompeuse.
    """

    model_info = show_payload.get("model_info")
    if not isinstance(model_info, dict):
        raise ContextPolicyError("model_info_absent")
    namespace = _text_namespace(model_info)
    derivations: list[str] = []
    layer_count = _namespace_number(model_info, namespace, "block_count")
    context_length = _namespace_number(model_info, namespace, "context_length")
    attention_heads = _namespace_number(model_info, namespace, "attention.head_count")
    kv_heads = _namespace_number(model_info, namespace, "attention.head_count_kv")
    if kv_heads is None and attention_heads is not None:
        # Borne supérieure prudente : une attention multi-query/groupée ne peut
        # pas avoir davantage de têtes KV que de têtes de requête.
        kv_heads = attention_heads
        derivations.append("kv_head_count_from_attention_head_count_upper_bound")
    key_length = _namespace_number(model_info, namespace, "attention.key_length")
    if key_length is None:
        embedding_length = _namespace_number(model_info, namespace, "embedding_length")
        if embedding_length is not None and attention_heads is not None:
            quotient = embedding_length / attention_heads
            if quotient.is_integer():
                key_length = quotient
                derivations.append("key_length_from_embedding_length_div_head_count")
    value_length = _namespace_number(model_info, namespace, "attention.value_length")
    if value_length is None:
        value_length = key_length
        if key_length is not None:
            derivations.append("value_length_from_key_length")
    if not all((layer_count, context_length, kv_heads, key_length, value_length)):
        raise ContextPolicyError("attention_shape_incomplete")

    attention_layer_count = layer_count
    attention_interval = _namespace_number(
        model_info, namespace, "full_attention_interval"
    )
    if attention_interval and attention_interval > 1:
        attention_layer_count = math.ceil(layer_count / attention_interval)
        derivations.append("attention_layer_count_from_full_attention_interval")

    hybrid_markers = (
        "recurrent",
        "state_space",
        "ssm",
        "attention.layer_count",
        "attention.sliding_window_pattern",
    )
    hybrid_keys = sorted(
        str(key)
        for key in model_info
        if str(key).startswith(f"{namespace}.")
        and any(marker in str(key).casefold() for marker in hybrid_markers)
    )
    return {
        "status": "estimated" if hybrid_keys or derivations else "calculated",
        "formula": "attention_layers * kv_heads * (key_length + value_length) * bytes_per_element",
        "metadata_namespace": namespace,
        "layer_count": int(layer_count),
        "attention_layer_count": int(attention_layer_count),
        "context_length": int(context_length),
        "kv_head_count": int(kv_heads),
        "key_length": int(key_length),
        "value_length": int(value_length),
        "derivations": derivations,
        "hybrid_metadata_keys": hybrid_keys,
    }


def kv_cache_bytes(
    shape: dict[str, Any],
    context_tokens: int,
    *,
    cache_type: str = "f16",
    parallel: int = 1,
) -> int:
    if cache_type not in KV_BYTES_PER_ELEMENT:
        raise ContextPolicyError("kv_cache_type_unsupported")
    if context_tokens <= 0 or parallel <= 0:
        raise ContextPolicyError("context_or_parallel_invalid")
    elements = (
        int(shape.get("attention_layer_count") or shape["layer_count"])
        * int(shape["kv_head_count"])
        * (int(shape["key_length"]) + int(shape["value_length"]))
        * int(context_tokens)
        * int(parallel)
    )
    return int(elements * KV_BYTES_PER_ELEMENT[cache_type])


def propose_context_candidates(
    show_payload: dict[str, Any],
    *,
    model_size_bytes: int,
    vram_budget_bytes: int,
    ram_available_bytes: int,
    requested_minimum: int = 32_768,
    parallel: int = 1,
) -> dict[str, Any]:
    """Produit au plus deux candidats calculés, jamais un balayage aveugle.

    Le premier vise une résidence GPU raisonnable en f16. Le second conserve, si
    la RAM le permet, le plancher agent avec q8_0. Tous deux restent des candidats
    jusqu'à confirmation par ``/api/ps`` et un test fonctionnel de rétention.
    """

    if min(model_size_bytes, vram_budget_bytes, ram_available_bytes) <= 0:
        raise ContextPolicyError("memory_budget_invalid")
    shape = extract_attention_shape(show_payload)
    max_context = int(shape["context_length"])
    candidates = [value for value in CONTEXT_CANDIDATES if value <= max_context]
    if not candidates:
        raise ContextPolicyError("model_context_capacity_unknown")

    # Une marge explicite couvre graphes, buffers de calcul et affichage. Elle ne
    # prétend pas prédire l'allocation interne d'Ollama : /api/ps reste l'oracle.
    compute_margin = max(384 * MIB, int(model_size_bytes * 0.12))
    estimates: list[dict[str, Any]] = []
    for cache_type in ("f16", "q8_0"):
        for tokens in candidates:
            kv_bytes = kv_cache_bytes(shape, tokens, cache_type=cache_type, parallel=parallel)
            projected = model_size_bytes + kv_bytes + compute_margin
            estimates.append(
                {
                    "context_tokens": tokens,
                    "kv_cache_type": cache_type,
                    "kv_cache_bytes": kv_bytes,
                    "projected_resident_bytes": projected,
                    "fits_vram_budget": projected <= vram_budget_bytes,
                    "fits_host_memory": projected <= ram_available_bytes,
                }
            )

    f16_fit = [item for item in estimates if item["kv_cache_type"] == "f16" and item["fits_vram_budget"]]
    selected: list[dict[str, Any]] = []
    if f16_fit:
        selected.append(max(f16_fit, key=lambda item: item["context_tokens"]))

    floor_q8 = [
        item
        for item in estimates
        if item["kv_cache_type"] == "q8_0"
        and item["context_tokens"] >= requested_minimum
        and item["fits_host_memory"]
    ]
    if floor_q8:
        selected.append(min(floor_q8, key=lambda item: item["context_tokens"]))
    elif not selected:
        host_fit = [item for item in estimates if item["kv_cache_type"] == "q8_0" and item["fits_host_memory"]]
        if host_fit:
            selected.append(max(host_fit, key=lambda item: item["context_tokens"]))

    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for item in selected:
        key = (int(item["context_tokens"]), str(item["kv_cache_type"]))
        if key not in seen:
            deduplicated.append(item)
            seen.add(key)
    return {
        "schema": "marvin.ollama-context-policy/1.0",
        "method": "analytical_then_runtime_verification",
        "attention_shape": shape,
        "model_max_context_tokens": max_context,
        "model_size_bytes": model_size_bytes,
        "vram_budget_bytes": vram_budget_bytes,
        "ram_available_bytes": ram_available_bytes,
        "parallel": parallel,
        "requested_minimum": requested_minimum,
        "candidates": deduplicated[:2],
        "all_estimates": estimates,
        "runtime_verification_required": True,
    }


def machine_profile_key(payload: dict[str, Any]) -> str:
    """Clé stable sans nom d'utilisateur ni identifiant matériel sensible."""

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
