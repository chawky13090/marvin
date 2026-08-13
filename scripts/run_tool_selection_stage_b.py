"""Exécute B1: choix natif d'outil sans jamais appeler un outil métier."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_prompt
import agent_tool_selection as selection
import database as db
import run_tool_selection_ablation as stage_a
import tool_router
from config import OLLAMA_URL, QDRANT_PATH

BASE = ROOT / "benchmarks/tool-selection/v1.2"
POLICY = BASE / "stage-b-preregistration.json"
HOLDOUT_FREEZE = BASE / "holdout-freeze-manifest.json"
CORPUS = BASE / "holdout-corpus.json"
ORACLE = BASE / "holdout-oracle.json"
RUNNER_FREEZE = BASE / "stage-b-runner-freeze.json"
AUTHORIZATION = BASE / "stage-b-b1-authorization.json"
RESULT = BASE / "stage-b-b1-result.json"
OLLAMA = OLLAMA_URL.rstrip("/")
FIXED_NOW = datetime(2026, 8, 13, 12, 0, 0)
CONFIGURATIONS = ("K+L+S", "K+S", "S")
CONFIRMATION_RE = re.compile(r"\b(?:confirm|autorisez|souhaitez-vous|puis-je)\b", re.IGNORECASE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def artifact_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def atomic(path: Path, value: Any) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(artifact_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _tool_call(message: dict[str, Any]) -> tuple[str | None, dict[str, Any], int]:
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or len(calls) != 1:
        return None, {}, len(calls) if isinstance(calls, list) else 0
    function = calls[0].get("function") or {}
    name = str(function.get("name") or "")
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    return name or None, arguments if isinstance(arguments, dict) else {}, 1


def _schema_valid(name: str | None, arguments: dict[str, Any], candidates: dict[str, dict[str, Any]]) -> bool:
    if not name or name not in candidates:
        return False
    schema = candidates[name].get("function", {}).get("parameters") or {"type": "object"}
    return not list(Draft202012Validator(schema).iter_errors(arguments))


def _accepted(name: str | None, arguments: dict[str, Any], accepted_calls: list[dict[str, Any]]) -> bool:
    if not name:
        return False
    for expected in accepted_calls:
        if name != expected["tool"]:
            continue
        if expected.get("action") is not None and arguments.get("action") != expected["action"]:
            continue
        valid = True
        for constraint in expected.get("constraints") or []:
            key = constraint["argument"]
            if constraint["operator"] == "present" and key not in arguments:
                valid = False
            if constraint["operator"] == "equals" and arguments.get(key) != constraint.get("value"):
                valid = False
        if valid:
            return True
    return False


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"median": 0.0, "p95": 0.0, "maximum": 0.0}
    index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {"median": round(statistics.median(ordered), 3), "p95": round(ordered[index], 3), "maximum": round(ordered[-1], 3)}


def _candidate_digest(candidates: dict[str, dict[str, dict[str, set[str]]]]) -> str:
    normalized = {
        mode: {
            configuration: {identity: sorted(names) for identity, names in sorted(rows.items())}
            for configuration, rows in sorted(configurations.items())
        }
        for mode, configurations in sorted(candidates.items())
    }
    return hashlib.sha256(canonical(normalized)).hexdigest()


async def _benchmark_call(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    *,
    model: str,
    system_prompt: str,
    prompt: str,
    tools: list[dict[str, Any]],
    options: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
        "tools": tools,
        "options": options,
    }
    assert "num_ctx" not in options
    started = time.perf_counter()
    async with semaphore:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = await client.post(f"{OLLAMA}/api/chat", json=payload)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError("Cloud 5xx", request=response.request, response=response)
                response.raise_for_status()
                body = response.json()
                message = body.get("message") or {}
                name, arguments, call_count = _tool_call(message)
                content = str(message.get("content") or "")
                return {
                    "observed_model": str(body.get("model") or ""),
                    "name": name,
                    "arguments": arguments,
                    "call_count": call_count,
                    "text_only": call_count == 0,
                    "confirmation_requested": bool(CONFIRMATION_RE.search(content)),
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "prompt_eval_count": int(body.get("prompt_eval_count") or 0),
                    "eval_count": int(body.get("eval_count") or 0),
                    "attempts": attempt,
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                }
            except (httpx.HTTPError, json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt < 3:
                    await asyncio.sleep(float(attempt))
        raise RuntimeError("Appel benchmark Cloud indisponible après trois tentatives bornées.") from last_error


async def run(*, preflight_only: bool) -> dict[str, Any]:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    holdout_freeze = json.loads(HOLDOUT_FREEZE.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))["items"]
    oracle_rows = json.loads(ORACLE.read_text(encoding="utf-8"))["items"]
    oracle = {row["id"]: row["accepted_calls"] for row in oracle_rows}
    for relative, expected in holdout_freeze["frozen_hashes"].items():
        if sha256(ROOT / relative) != expected:
            raise RuntimeError(f"Holdout gelé modifié: {relative}")
    for relative, expected in policy["product_sources_sha256"].items():
        if sha256(ROOT / relative) != expected:
            raise RuntimeError(f"Produit modifié depuis le pré-enregistrement: {relative}")

    records = [{"id": row["id"], "query": row["prompt"]} for row in corpus]
    client = QdrantClient(path=QDRANT_PATH)
    try:
        collections = {item.name for item in client.get_collections().collections}
        if tool_router._TOOL_COLLECTION not in collections:
            raise RuntimeError("Index sémantique des outils absent.")
        expected_index = tool_router.tool_index_fingerprint(selection.TOOLS_SPEC)
        if db.get_setting("tool_index_hash") != expected_index:
            raise RuntimeError("Index sémantique des outils périmé.")
        lexical, semantic, signal_metadata = await stage_a._signals(records, client, batch_size=16, control_query_count=5)
    finally:
        client.close()

    all_candidates, all_costs = await stage_a._candidate_matrix(
        records,
        modes={name: int(value) for name, value in policy["experiment"]["modes"].items()},
        lexical_cache=lexical,
        semantic_cache=semantic,
    )
    candidates = {
        mode: {configuration: rows for configuration, rows in configurations.items() if configuration in CONFIGURATIONS}
        for mode, configurations in all_candidates.items()
    }
    candidate_spec: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    spec_by_name = {str(row["function"]["name"]): row for row in selection.TOOLS_SPEC}
    for mode, configurations in candidates.items():
        for configuration, by_id in configurations.items():
            for identity, names in by_id.items():
                candidate_spec[(mode, configuration, identity)] = [row for row in selection.TOOLS_SPEC if row["function"]["name"] in names]

    system_prompt = agent_prompt.build_system_prompt([], 2, now=FIXED_NOW, compact=False)
    candidate_matrix_sha256 = _candidate_digest(candidates)

    preflight = {
        "status": "preflight_complete",
        "record_count": len(records),
        "candidate_matrix_cells": len(candidate_spec),
        "signal_metadata": signal_metadata,
        "tool_index_fingerprint": tool_router.tool_index_fingerprint(selection.TOOLS_SPEC),
        "candidate_matrix_sha256": candidate_matrix_sha256,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        "business_tool_execution_count": 0,
        "benchmark_model_invocation_count": 0,
    }
    if preflight_only:
        return preflight

    runner_freeze = json.loads(RUNNER_FREEZE.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    if RESULT.exists():
        raise RuntimeError("Résultat B1 déjà publié; autorisation à usage unique consommée.")
    for relative, expected in runner_freeze["frozen_hashes"].items():
        if sha256(ROOT / relative) != expected:
            raise RuntimeError(f"Runner gelé modifié: {relative}")
    if authorization["runner_freeze_sha256"] != sha256(RUNNER_FREEZE):
        raise RuntimeError("Autorisation non liée au gel du runner.")
    if not authorization["benchmark_model_execution_authorized"] or authorization["business_tool_execution_authorized"]:
        raise RuntimeError("Autorisation B1 invalide.")

    benchmark = policy["independent_roles"]["benchmark"]
    async with httpx.AsyncClient(timeout=600, trust_env=False) as http:
        tags = (await http.get(f"{OLLAMA}/api/tags")).json().get("models") or []
        row = next((item for item in tags if item.get("name") == benchmark["model"]), None)
        if not row or row.get("digest") != benchmark["digest"] or not row.get("remote_host"):
            raise RuntimeError("Provenance du modèle benchmark invalide.")
        semaphore = asyncio.Semaphore(int(policy["experiment"]["concurrency_maximum"]))
        tasks, descriptors = [], []
        configurations = list(policy["experiment"]["configurations"])
        for item_index, item in enumerate(corpus):
            for repetition in range(int(policy["experiment"]["repetitions_per_intent"])):
                rotated = configurations[item_index % len(configurations):] + configurations[:item_index % len(configurations)]
                for mode in policy["experiment"]["modes"]:
                    for configuration in rotated:
                        specs = candidate_spec[(mode, configuration, item["id"])]
                        descriptors.append((item, repetition + 1, mode, configuration, specs))
                        tasks.append(_benchmark_call(
                            http, semaphore, model=benchmark["model"], system_prompt=system_prompt,
                            prompt=item["prompt"], tools=specs,
                            options={"temperature": policy["experiment"]["temperature"], "top_p": policy["experiment"]["top_p"], "seed": policy["experiment"]["seed"], "num_predict": 512},
                        ))
        raw = await asyncio.gather(*tasks)

    observations = []
    for descriptor, observed in zip(descriptors, raw, strict=True):
        item, repetition, mode, configuration, specs = descriptor
        by_name = {str(spec["function"]["name"]): spec for spec in specs}
        name, arguments = observed["name"], observed["arguments"]
        observed.update({
            "id": item["id"], "family": item["family"], "repetition": repetition,
            "mode": mode, "configuration": configuration,
            "candidate_count": len(specs), "prompt_schema_bytes": len(canonical(specs)),
            "public_tool_name_valid": name is None or name in spec_by_name,
            "candidate_membership_valid": name is None or name in by_name,
            "argument_schema_valid": _schema_valid(name, arguments, by_name),
            "argument_schema_assessed": observed["call_count"] == 1 and name in by_name,
            "oracle_candidate_present": any(call["tool"] in by_name for call in oracle[item["id"]]),
            "accepted_tool_action": _accepted(name, arguments, oracle[item["id"]]),
            "normalized_choice_sha256": hashlib.sha256(canonical({"name": name, "arguments": arguments})).hexdigest(),
        })
        observations.append(observed)

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        grouped[(row["id"], row["family"], row["mode"], row["configuration"])].append(row)
    aggregates: dict[str, Any] = {}
    for mode in policy["experiment"]["modes"]:
        aggregates[mode] = {}
        for configuration in CONFIGURATIONS:
            subset = [row for row in observations if row["mode"] == mode and row["configuration"] == configuration]
            families = {}
            for family in policy["holdout"]["families"]:
                rows = [row for row in subset if row["family"] == family]
                families[family] = {"accepted": sum(row["accepted_tool_action"] for row in rows), "total": len(rows), "rate": round(sum(row["accepted_tool_action"] for row in rows) / len(rows), 6)}
            stable = [len({row["normalized_choice_sha256"] for row in rows}) == 1 for key, rows in grouped.items() if key[2:] == (mode, configuration)]
            argument_rows = [row for row in subset if row["argument_schema_assessed"]]
            aggregates[mode][configuration] = {
                "accepted": sum(row["accepted_tool_action"] for row in subset), "total": len(subset),
                "accepted_rate": round(sum(row["accepted_tool_action"] for row in subset) / len(subset), 6),
                "families": families,
                "tool_name_validity_rate": round(sum(row["public_tool_name_valid"] for row in subset) / len(subset), 6),
                "invalid_public_tool_name_count": sum(not row["public_tool_name_valid"] for row in subset),
                "argument_schema_assessed_count": len(argument_rows),
                "argument_schema_validity_rate": round(sum(row["argument_schema_valid"] for row in argument_rows) / len(argument_rows), 6) if argument_rows else None,
                "candidate_set_recall_rate": round(sum(row["oracle_candidate_present"] for row in subset) / len(subset), 6),
                "text_only_rate": round(sum(row["text_only"] for row in subset) / len(subset), 6),
                "repeat_stability_rate": round(sum(stable) / len(stable), 6),
                "confirmation_count": sum(row["confirmation_requested"] for row in subset),
                "latency_ms": _summary([row["latency_ms"] for row in subset]),
                "prompt_schema_bytes": _summary([float(row["prompt_schema_bytes"]) for row in subset]),
                "candidate_count": _summary([float(row["candidate_count"]) for row in subset]),
            }

    result = {
        "schema": "marvin.tool-selection-stage-b-b1-result/1.0", "status": "complete",
        "policy_sha256": sha256(POLICY), "holdout_freeze_sha256": sha256(HOLDOUT_FREEZE),
        "runner_freeze_sha256": sha256(RUNNER_FREEZE), "authorization_sha256": sha256(AUTHORIZATION),
        "runner_sha256": sha256(Path(__file__)), "benchmark_model": benchmark,
        "benchmark_model_observed": sorted({row["observed_model"] for row in observations}),
        "client_num_ctx": None, "business_tool_execution_count": 0, "host_side_effect_count": 0,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        "candidate_matrix_sha256": candidate_matrix_sha256,
        "observations": observations, "aggregates": aggregates,
    }
    atomic(RESULT, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run(preflight_only=args.preflight_only))
    print(json.dumps({key: result[key] for key in ("status", "business_tool_execution_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
