"""Exécute l'ablation déterministe K/L/S sans appel au LLM de conversation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_tool_selection as selection
import database as db
import dpapi_secret_store
import real_usage_corpus
import tool_router
import vector_store as vs
from config import EMBEDDING_MODEL, OLLAMA_URL, QDRANT_PATH
from qdrant_client import QdrantClient
from tool_availability import ConnectivitySnapshot


BASE_POLICY = ROOT / "benchmarks" / "tool-selection" / "v1.0" / "ablation-preregistration.json"
POLICY = ROOT / "benchmarks" / "tool-selection" / "v1.1" / "ablation-reauthorization.json"
PUBLIC_CACHE = ROOT / "benchmarks" / "tool-selection" / "v1.1" / "public-semantic-signal-cache.json"
RESULT = ROOT / "benchmarks" / "tool-selection" / "v1.1" / "ablation-result.json"
CONFIGURATIONS = ("K", "L", "S", "K+L", "K+S", "L+S", "K+L+S")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _artifact_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_artifact_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _unprotect(path: Path) -> Any:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    return real_usage_corpus.unprotect_payload(
        envelope,
        unprotect=lambda value, purpose: dpapi_secret_store.unprotect_bytes(
            value,
            purpose=purpose,
        ),
    )


def _tool_digest() -> str:
    return _digest(selection.TOOLS_SPEC)


async def _ollama_embedding_identity() -> dict[str, str]:
    import httpx

    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        response = await client.get(f"{OLLAMA_URL.rstrip('/')}/api/tags")
        response.raise_for_status()
        models = response.json().get("models") or []
    target = str(EMBEDDING_MODEL)
    row = next(
        (
            item
            for item in models
            if str(item.get("name") or "") == target
            or str(item.get("model") or "") == target
            or str(item.get("name") or "").split(":", 1)[0] == target.split(":", 1)[0]
        ),
        None,
    )
    if row is None:
        raise RuntimeError("Modèle d'embedding gelé introuvable dans Ollama.")
    return {
        "model": str(row.get("name") or row.get("model") or target),
        "digest": str(row.get("digest") or ""),
    }


def _public_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    intent = json.loads(
        (ROOT / "benchmarks/windows-operator/v1.1/intent-corpus.json").read_text(
            encoding="utf-8"
        )
    )
    matrix = json.loads(
        (
            ROOT
            / "benchmarks/windows-operator/v1.1/routing-capability-contracts-retrospective-v1.json"
        ).read_text(encoding="utf-8")
    )
    accepted_by_family: dict[str, set[str]] = {}
    for contract in matrix["contracts"].values():
        family = str(contract["family"])
        accepted_by_family.setdefault(family, set()).update(
            str(item["name"]) for item in contract["accepted"]
        )
    correctness = []
    for item in intent["items"]:
        family = str(item["family"])
        accepted = sorted(accepted_by_family.get(family, set()))
        correctness.append(
            {
                "id": str(item["id"]),
                "query": str(item["prompt"]),
                "family": family,
                "accepted": accepted,
                "assessed": bool(accepted),
            }
        )
    recovery_source = json.loads(
        (ROOT / "benchmarks/tool-recovery/v1.2/development-corpus.json").read_text(
            encoding="utf-8"
        )
    )
    recovery = [
        {
            "id": str(item["id"]),
            "query": str(item["unknown_name"]).replace("_", " "),
            "family": str(item["family"]),
            "accepted": sorted(str(name) for name in item["acceptable_tools"]),
            "assessed": bool(item["acceptable_tools"]),
        }
        for item in recovery_source["items"]
    ]
    return correctness, recovery


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"median": 0.0, "p95": 0.0, "maximum": 0.0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {
        "median": round(float(statistics.median(ordered)), 3),
        "p95": round(float(ordered[p95_index]), 3),
        "maximum": round(float(ordered[-1]), 3),
    }


async def _embed_batches(
    records: list[dict[str, Any]],
    *,
    batch_size: int,
    control_query_count: int,
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    import httpx

    vectors: dict[str, list[float]] = {}
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        for offset in range(0, len(records), batch_size):
            chunk = records[offset : offset + batch_size]
            queries = [str(record["query"]) for record in chunk]
            response = await client.post(
                f"{OLLAMA_URL.rstrip('/')}/api/embed",
                json={"model": EMBEDDING_MODEL, "input": queries},
            )
            response.raise_for_status()
            embeddings = response.json().get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(chunk):
                raise RuntimeError("Lot d'embeddings Ollama incomplet.")
            for record, vector in zip(chunk, embeddings, strict=True):
                if not isinstance(vector, list) or not vector:
                    raise RuntimeError("Vecteur d'embedding invalide.")
                key = hashlib.sha256(str(record["query"]).encode("utf-8")).hexdigest()
                vectors[key] = [float(value) for value in vector]
            print(
                f"embeddings {min(offset + len(chunk), len(records))}/{len(records)}",
                flush=True,
            )
    controls = records[:control_query_count]
    if len(controls) < control_query_count:
        raise RuntimeError("Moins de cinq requêtes de contrôle pour le batching.")
    for record in controls:
        key = hashlib.sha256(str(record["query"]).encode("utf-8")).hexdigest()
        single = await vs.embed(str(record["query"]))
        if single != vectors[key]:
            raise RuntimeError("Embedding unitaire et embedding en lot divergents.")
    return vectors, {
        "batch_size": batch_size,
        "record_count": len(records),
        "control_query_count": len(controls),
        "single_batch_exact_equality": True,
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


async def _signals(
    records: list[dict[str, Any]],
    client: QdrantClient,
    *,
    batch_size: int,
    control_query_count: int,
) -> tuple[
    dict[str, list[tuple[str, float]]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    lexical: dict[str, list[tuple[str, float]]] = {}
    semantic: dict[str, dict[str, Any]] = {}
    vectors, embedding_metadata = await _embed_batches(
        records,
        batch_size=batch_size,
        control_query_count=control_query_count,
    )
    started = time.perf_counter()
    for index, record in enumerate(records, start=1):
        query = str(record["query"])
        key = hashlib.sha256(query.encode("utf-8")).hexdigest()
        lexical[key] = selection.rank_capabilities(query, selection._CAPABILITY_CATALOG)
        vector = vectors[key]
        tool_response = client.query_points(
            collection_name=tool_router._TOOL_COLLECTION,
            query=vector,
            limit=8,
            with_payload=True,
        )
        semantic_scores = {
            str(hit.payload.get("name")): float(hit.score)
            for hit in tool_response.points
            if hit.payload.get("name") and float(hit.score) >= 0.40
        }
        feedback_response = client.query_points(
            collection_name=tool_router._FEEDBACK_COLLECTION,
            query=vector,
            limit=5,
            with_payload=True,
        )
        learned = {
            str(hit.payload.get("tool"))
            for hit in feedback_response.points
            if hit.payload.get("tool") and float(hit.score) >= 0.72
        }
        semantic[key] = {
            "semantic": sorted(semantic_scores),
            "learned": sorted(learned),
            "semantic_scores": {
                name: round(score, 8)
                for name, score in sorted(semantic_scores.items())
            },
        }
        if index % 50 == 0 or index == len(records):
            print(f"signaux {index}/{len(records)}", flush=True)

    original_get_client = vs.get_client
    vs.get_client = lambda: client
    try:
        for record in records[:control_query_count]:
            query = str(record["query"])
            key = hashlib.sha256(query.encode("utf-8")).hexdigest()
            routed = await tool_router.route_tools(query)
            reference = {
                "semantic": sorted(str(name) for name in routed.get("semantic", set())),
                "learned": sorted(str(name) for name in routed.get("learned", set())),
                "semantic_scores": {
                    str(name): round(float(score), 8)
                    for name, score in sorted((routed.get("semantic_scores") or {}).items())
                },
            }
            if reference != semantic[key]:
                raise RuntimeError("Signal routé unitaire et signal en lot divergents.")
    finally:
        vs.get_client = original_get_client
    return lexical, semantic, {
        "embedding": embedding_metadata,
        "qdrant_and_lexical_duration_ms": round(
            (time.perf_counter() - started) * 1000.0,
            3,
        ),
        "route_control_query_count": control_query_count,
        "route_control_exact_equality": True,
    }


async def _candidate_matrix(
    records: list[dict[str, Any]],
    *,
    modes: dict[str, int],
    lexical_cache: dict[str, list[tuple[str, float]]],
    semantic_cache: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[str, dict[str, set[str]]]],
    dict[str, dict[str, dict[str, dict[str, float]]]],
]:
    candidates: dict[str, dict[str, dict[str, set[str]]]] = {
        mode: {configuration: {} for configuration in CONFIGURATIONS}
        for mode in modes
    }
    costs: dict[str, dict[str, dict[str, dict[str, float]]]] = {
        mode: {configuration: {} for configuration in CONFIGURATIONS}
        for mode in modes
    }
    original_keywords = selection._KEYWORD_TOOLS_NORM
    original_rank = selection.rank_capabilities
    original_setting = selection.db.get_setting
    original_snapshot = selection.tool_availability.get_snapshot
    original_route = tool_router.route_tools
    context: dict[str, Any] = {"configuration": "K+L+S", "budget": 40}
    snapshot = ConnectivitySnapshot(
        internet=True,
        services={"ollama": True, "searxng": True},
        observed_at=0.0,
    )

    def cached_rank(query: str, _catalog, **_kwargs):
        if "L" not in context["configuration"]:
            return []
        return lexical_cache[hashlib.sha256(str(query).encode("utf-8")).hexdigest()]

    async def cached_route(query: str, **_kwargs):
        if "S" not in context["configuration"]:
            return {"semantic": set(), "learned": set(), "semantic_scores": {}}
        value = semantic_cache[hashlib.sha256(str(query).encode("utf-8")).hexdigest()]
        return {
            "semantic": set(value["semantic"]),
            "learned": set(value["learned"]),
            "semantic_scores": dict(value["semantic_scores"]),
        }

    def fixed_setting(key: str):
        if key == "max_tools":
            return context["budget"]
        return original_setting(key)

    async def fixed_snapshot(*, force: bool = False):
        del force
        return snapshot

    selection.rank_capabilities = cached_rank
    selection.db.get_setting = fixed_setting
    selection.tool_availability.get_snapshot = fixed_snapshot
    tool_router.route_tools = cached_route
    try:
        for mode, budget in modes.items():
            context["budget"] = int(budget)
            for configuration in CONFIGURATIONS:
                context["configuration"] = configuration
                selection._KEYWORD_TOOLS_NORM = original_keywords if "K" in configuration else ()
                for record in records:
                    started = time.perf_counter()
                    specifications = await selection.filter_relevant_tools(
                        [{"role": "user", "content": record["query"]}],
                        "agent",
                    )
                    duration_ms = (time.perf_counter() - started) * 1000.0
                    names = {
                        str(item.get("function", {}).get("name") or "")
                        for item in specifications
                    }
                    candidates[mode][configuration][record["id"]] = names
                    costs[mode][configuration][record["id"]] = {
                        "candidate_count": float(len(names)),
                        "schema_bytes": float(len(_canonical(specifications))),
                        "duration_ms": duration_ms,
                    }
    finally:
        selection._KEYWORD_TOOLS_NORM = original_keywords
        selection.rank_capabilities = original_rank
        selection.db.get_setting = original_setting
        selection.tool_availability.get_snapshot = original_snapshot
        tool_router.route_tools = original_route
    return candidates, costs


def _correctness_panel(
    records: list[dict[str, Any]],
    candidates: dict[str, dict[str, dict[str, set[str]]]],
    costs: dict[str, Any],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for mode, configurations in candidates.items():
        output[mode] = {}
        for configuration, by_id in configurations.items():
            family_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"hits": 0, "total": 0})
            hits = total = 0
            for record in records:
                if not record["assessed"]:
                    continue
                matched = bool(set(record["accepted"]) & by_id[record["id"]])
                family = family_counts[record["family"]]
                family["total"] += 1
                family["hits"] += int(matched)
                total += 1
                hits += int(matched)
            panel_costs = [
                costs[mode][configuration][record["id"]]
                for record in records
            ]
            output[mode][configuration] = {
                "hits": hits,
                "total": total,
                "recall": round(hits / total, 6) if total else None,
                "by_family": {
                    family: {
                        **counts,
                        "recall": round(counts["hits"] / counts["total"], 6),
                        "state": "ASSESSED" if counts["total"] >= 5 else "UNASSESSED",
                    }
                    for family, counts in sorted(family_counts.items())
                },
                "costs": {
                    metric: _summary([sample[metric] for sample in panel_costs])
                    for metric in ("candidate_count", "schema_bytes", "duration_ms")
                },
            }
    return output


def _private_panel(
    provenance: list[dict[str, Any]],
    candidates: dict[str, dict[str, dict[str, set[str]]]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for mode, configurations in candidates.items():
        output[mode] = {}
        for configuration, by_id in configurations.items():
            all_pairs: set[tuple[str, str]] = set()
            successful_pairs: set[tuple[str, str]] = set()
            for record in provenance:
                opaque_id = str(record["id"])
                for execution in record.get("executions") or []:
                    pair = (opaque_id, str(execution.get("tool") or ""))
                    if pair[1]:
                        all_pairs.add(pair)
                        if execution.get("success") is True:
                            successful_pairs.add(pair)
            all_hits = sum(tool in by_id[message_id] for message_id, tool in all_pairs)
            successful_hits = sum(
                tool in by_id[message_id] for message_id, tool in successful_pairs
            )
            output[mode][configuration] = {
                "historical_pairs": len(all_pairs),
                "retained_pairs": all_hits,
                "retention": round(all_hits / len(all_pairs), 6) if all_pairs else None,
                "successful_historical_pairs": len(successful_pairs),
                "retained_successful_pairs": successful_hits,
                "successful_retention": round(
                    successful_hits / len(successful_pairs), 6
                ) if successful_pairs else None,
            }
    return output


def _layer_decisions(public: dict[str, Any], private: dict[str, Any]) -> dict[str, Any]:
    removals = {"K": "L+S", "L": "K+S", "S": "K+L"}
    decisions: dict[str, Any] = {}
    for layer, without in removals.items():
        deltas: list[dict[str, Any]] = []
        for mode, configurations in public.items():
            full = configurations["K+L+S"]
            ablated = configurations[without]
            families = sorted(set(full["by_family"]) | set(ablated["by_family"]))
            for family in families:
                left = full["by_family"].get(family)
                right = ablated["by_family"].get(family)
                if not left or not right or left["state"] != "ASSESSED" or right["state"] != "ASSESSED":
                    continue
                delta = round(left["recall"] - right["recall"], 6)
                if delta:
                    deltas.append({"mode": mode, "family": family, "recall_delta": delta})
            if private:
                private_delta = round(
                    private[mode]["K+L+S"]["successful_retention"]
                    - private[mode][without]["successful_retention"],
                    6,
                )
                if private_delta:
                    deltas.append(
                        {"mode": mode, "family": "PRIVATE_COMPATIBILITY", "recall_delta": private_delta}
                    )
        positive = [item for item in deltas if item["recall_delta"] > 0]
        negative = [item for item in deltas if item["recall_delta"] < 0]
        decisions[layer] = {
            "without_configuration": without,
            "positive_contributions": positive,
            "negative_contributions": negative,
            "stage_a_state": (
                "REQUIRED_FOR_STAGE_B"
                if positive
                else "TRADEOFF_REQUIRES_STAGE_B"
                if negative
                else "REDUNDANT_CANDIDATE_REQUIRES_STAGE_B"
            ),
            "product_change_authorized": False,
        }
    return decisions


async def run(*, public_only: bool, output: Path, cache_output: Path) -> dict[str, Any]:
    total_started = time.perf_counter()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    base_policy = json.loads(BASE_POLICY.read_text(encoding="utf-8"))
    if policy["status"] != "frozen_after_behavior_equivalent_product_optimization":
        raise RuntimeError("Régel d'ablation v1.1 invalide.")
    if _sha256(BASE_POLICY) != policy["inherits"]["sha256"]:
        raise RuntimeError("Pré-enregistrement d'ablation v1.0 modifié.")
    if not policy["inherits"][
        "all_datasets_modes_configurations_metrics_and_decision_rules_unchanged"
    ]:
        raise RuntimeError("Le protocole v1.0 n'est pas intégralement hérité.")
    runner_authorization = policy["runner_v1_1_authorization"]
    batch_size = int(runner_authorization["embedding_batch_maximum"])
    control_query_count = int(runner_authorization["control_query_minimum"])
    if not 1 <= batch_size <= 32 or control_query_count < 5:
        raise RuntimeError("Autorisation de batching hors limites.")
    expected_output = (ROOT / policy["outputs"]["result"]).resolve()
    expected_cache = (ROOT / policy["outputs"]["public_cache"]).resolve()
    if output.resolve() != expected_output or cache_output.resolve() != expected_cache:
        raise RuntimeError("Chemin de publication différent du régèle v1.1.")
    if output.exists() or cache_output.exists():
        raise RuntimeError("Résultat v1.1 déjà publié; écrasement interdit.")
    for relative_path, expected in policy["product_sources_sha256"].items():
        if _sha256(ROOT / relative_path) != expected:
            raise RuntimeError(f"Source produit modifiée depuis le gel : {relative_path}")
    for relative_path, expected in base_policy["public_inputs_sha256"].items():
        if _sha256(ROOT / relative_path) != expected:
            raise RuntimeError(f"Entrée publique modifiée : {relative_path}")
    correctness, recovery = _public_records()
    private_texts: list[dict[str, Any]] = []
    if not public_only:
        for item in base_policy["private_inputs"].values():
            if isinstance(item, dict) and "path" in item:
                path = ROOT / item["path"]
                if not path.exists() or _sha256(path) != item["sha256"]:
                    raise RuntimeError("Enveloppe privée absente ou modifiée.")
        private_texts = _unprotect(
            ROOT / base_policy["private_inputs"]["text_envelope"]["path"]
        )
        if not isinstance(private_texts, list) or len(private_texts) != 392:
            raise RuntimeError("Corpus texte privé inattendu.")
        if len({str(item["id"]) for item in private_texts}) != len(private_texts):
            raise RuntimeError("Identifiants privés dupliqués.")

    all_records = correctness + recovery + [
        {"id": str(item["id"]), "query": str(item["text"])}
        for item in private_texts
    ]
    unique_records: dict[str, dict[str, Any]] = {}
    for record in all_records:
        key = hashlib.sha256(str(record["query"]).encode("utf-8")).hexdigest()
        unique_records.setdefault(key, record)

    client = QdrantClient(path=QDRANT_PATH)
    try:
        collections = {item.name for item in client.get_collections().collections}
        if "tool_index" not in collections:
            raise RuntimeError("Index sémantique des outils absent; aucun écrit automatique autorisé.")
        expected_index = tool_router.tool_index_fingerprint(selection.TOOLS_SPEC)
        if db.get_setting("tool_index_hash") != expected_index:
            raise RuntimeError("Empreinte de l'index sémantique périmée; régénération hors campagne requise.")
        embedding = await _ollama_embedding_identity()
        lexical, semantic, signal_metadata = await _signals(
            list(unique_records.values()),
            client,
            batch_size=batch_size,
            control_query_count=control_query_count,
        )
    finally:
        client.close()

    modes = {str(name): int(limit) for name, limit in base_policy["modes"].items()}
    public_selection_started = time.perf_counter()
    public_candidates, public_costs = await _candidate_matrix(
        correctness + recovery,
        modes=modes,
        lexical_cache=lexical,
        semantic_cache=semantic,
    )
    public_selection_duration_ms = round(
        (time.perf_counter() - public_selection_started) * 1000.0,
        3,
    )
    correctness_candidates = {
        mode: {
            configuration: {
                record["id"]: values[record["id"]]
                for record in correctness
            }
            for configuration, values in configurations.items()
        }
        for mode, configurations in public_candidates.items()
    }
    recovery_candidates = {
        mode: {
            configuration: {
                record["id"]: values[record["id"]]
                for record in recovery
            }
            for configuration, values in configurations.items()
        }
        for mode, configurations in public_candidates.items()
    }
    public_panel = _correctness_panel(correctness, correctness_candidates, public_costs)
    recovery_panel = _correctness_panel(recovery, recovery_candidates, public_costs)

    private_panel: dict[str, Any] = {}
    private_selection_duration_ms: float | None = None
    if private_texts:
        private_selection_started = time.perf_counter()
        private_candidates, _private_costs = await _candidate_matrix(
            [{"id": str(item["id"]), "query": str(item["text"])} for item in private_texts],
            modes=modes,
            lexical_cache=lexical,
            semantic_cache=semantic,
        )
        private_selection_duration_ms = round(
            (time.perf_counter() - private_selection_started) * 1000.0,
            3,
        )
        # La provenance n'est déchiffrée qu'après le calcul complet des candidats.
        provenance = _unprotect(
            ROOT / base_policy["private_inputs"]["provenance_envelope"]["path"]
        )
        if {item["id"] for item in private_texts} != {item["id"] for item in provenance}:
            raise RuntimeError("Liaison privée texte/provenance incohérente.")
        private_panel = _private_panel(provenance, private_candidates)

    public_cache = {
        "schema": "marvin.tool-selection-public-semantic-cache/1.1",
        "source_policy_sha256": _sha256(POLICY),
        "inherited_policy_sha256": _sha256(BASE_POLICY),
        "embedding": embedding,
        "tool_index_fingerprint": tool_router.tool_index_fingerprint(selection.TOOLS_SPEC),
        "tool_spec_sha256": _tool_digest(),
        "records": {
            record["id"]: semantic[
                hashlib.sha256(str(record["query"]).encode("utf-8")).hexdigest()
            ]
            for record in correctness + recovery
        },
    }
    public_cache_sha256 = hashlib.sha256(_artifact_bytes(public_cache)).hexdigest()
    result = {
        "schema": "marvin.tool-selection-ablation-result/1.1",
        "status": "complete_private_and_public" if private_panel else "complete_public_only",
        "source_policy_sha256": _sha256(POLICY),
        "inherited_policy_sha256": _sha256(BASE_POLICY),
        "source_commit": policy["source_commit"],
        "runner_sha256": _sha256(Path(__file__)),
        "runner_product_change": False,
        "chat_llm_calls": 0,
        "business_tool_executions": 0,
        "embedding": embedding,
        "tool_index_fingerprint": tool_router.tool_index_fingerprint(selection.TOOLS_SPEC),
        "tool_spec_sha256": _tool_digest(),
        "public_cache_sha256": public_cache_sha256,
        "phase_durations_ms": {
            "signals": signal_metadata,
            "public_candidate_selection": public_selection_duration_ms,
            "private_candidate_selection": private_selection_duration_ms,
            "total_before_result_write": round(
                (time.perf_counter() - total_started) * 1000.0,
                3,
            ),
        },
        "public_correctness": public_panel,
        "public_recovery_canary": recovery_panel,
        "private_compatibility": private_panel,
        "private_interpretation": (
            "historical_execution_retention_not_correctness"
            if private_panel
            else "UNASSESSED_PRIVATE_INPUT_ABSENT"
        ),
        "layer_decisions": _layer_decisions(public_panel, private_panel),
        "limitations": [
            "The public correctness panel is retrospective and burned; it cannot estimate generalization.",
            "The private panel measures retention of historical executions, never whether those executions were correct.",
            "Semantic and learned signals are frozen observations of the current local index and feedback state.",
            "Stage A cannot authorize product layer removal or a new canonical capability facade.",
        ],
        "next_step": "stage_b_on_new_independent_holdout_for_surviving_configurations",
    }
    try:
        _write_atomic(cache_output, public_cache)
        _write_atomic(output, result)
    except Exception:
        cache_output.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--output", type=Path, default=RESULT)
    parser.add_argument("--cache-output", type=Path, default=PUBLIC_CACHE)
    args = parser.parse_args()
    value = asyncio.run(
        run(
            public_only=bool(args.public_only),
            output=args.output,
            cache_output=args.cache_output,
        )
    )
    print(
        "Tool Selection Ablation complete - "
        f"status={value['status']} decisions="
        + json.dumps(
            {key: item["stage_a_state"] for key, item in value["layer_decisions"].items()},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
