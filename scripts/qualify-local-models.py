"""Qualifie les modeles agents Ollama locaux sur la machine courante."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import auto_config  # noqa: E402
import local_model_policy  # noqa: E402
import local_model_qualification as qualification  # noqa: E402


TOOL = {
    "type": "function",
    "function": {
        "name": "local_probe",
        "description": "Retourne le produit exact de deux entiers.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
}


def _request(url: str, payload: dict[str, Any] | None = None, timeout: int = 240) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if payload is not None else "GET",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.load(response)
    return value if isinstance(value, dict) else {}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _inventory(base_url: str) -> tuple[str, list[dict[str, Any]]]:
    version = str(_request(f"{base_url}/api/version").get("version") or "")
    result: list[dict[str, Any]] = []
    for item in _request(f"{base_url}/api/tags").get("models") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not local_model_policy.MODEL_NAME_RE.fullmatch(name) or name.endswith((":cloud", "-cloud")):
            continue
        show = _request(f"{base_url}/api/show", {"model": name, "verbose": False})
        result.append({
            "name": name,
            "digest": str(item.get("digest") or ""),
            "size_bytes": int(item.get("size") or 0),
            "capabilities": sorted(str(value).casefold() for value in show.get("capabilities") or []),
        })
    return version, result


def _candidate_models(models: list[dict[str, Any]], hardware: dict[str, Any], requested: list[str]) -> list[dict[str, Any]]:
    budget = local_model_policy.memory_budget_bytes(hardware)
    requested_names = {local_model_policy.canonical_name(value) for value in requested}
    candidates = []
    for item in models:
        name = local_model_policy.canonical_name(item["name"])
        capabilities = set(item.get("capabilities") or [])
        excluded = any(marker in name.casefold() for marker in ("embed", "ocr", "coder"))
        if (
            int(item.get("size_bytes") or 0) <= budget
            and "tools" in capabilities
            and not excluded
            and (not requested_names or name in requested_names)
        ):
            candidates.append(item)
    candidates.sort(key=lambda item: (int(item["size_bytes"]), item["name"]))
    if requested_names - {local_model_policy.canonical_name(item["name"]) for item in candidates}:
        raise ValueError("Un modele demande est absent, trop volumineux ou sans capacite tools.")
    return candidates[:6]


def _run_once(base_url: str, model: str) -> dict[str, Any]:
    base = {
        "model": model,
        "stream": False,
        "keep_alive": "10m",
        "tools": [TOOL],
        "options": {"num_ctx": 8192, "temperature": 0, "top_p": 0.9},
    }
    messages = [
        {"role": "system", "content": "Appelle local_probe puis reponds uniquement avec son resultat."},
        {"role": "user", "content": "Calcule exactement 37 multiplie par 43."},
    ]
    started = time.monotonic()
    first = _request(f"{base_url}/api/chat", {**base, "messages": messages})
    calls = (first.get("message") or {}).get("tool_calls") or []
    function = (calls[0].get("function") or {}) if calls else {}
    arguments = function.get("arguments") or {}
    tool_ok = function.get("name") == "local_probe" and arguments == {"a": 37, "b": 43}
    messages.extend([first.get("message") or {}, {"role": "tool", "tool_name": "local_probe", "content": "1591"}])
    second = _request(f"{base_url}/api/chat", {**base, "messages": messages})
    final = str((second.get("message") or {}).get("content") or "").strip()
    final_contract_passed = re.search(r"(?<!\d)1591(?!\d)", final) is not None
    return {
        "success": bool(tool_ok and final_contract_passed),
        "tool_call_passed": bool(tool_ok),
        "final_contract_passed": final_contract_passed,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }


def _unload(base_url: str, model: str) -> None:
    try:
        _request(f"{base_url}/api/generate", {"model": model, "keep_alive": 0, "prompt": ""}, timeout=30)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--output", default=str(qualification.PROFILE_PATH))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--model", action="append", default=[])
    args = parser.parse_args()
    repetitions = max(3, min(int(args.repetitions), 5))
    output = Path(args.output).resolve()
    allowed_root = (ROOT / "data" / "install").resolve()
    if allowed_root not in output.parents or output.suffix.casefold() != ".json":
        raise ValueError("La preuve doit etre un JSON sous data/install.")

    base_url = str(args.ollama_url).rstrip("/")
    hardware = auto_config.detect_hardware()
    ollama_version, installed = _inventory(base_url)
    candidates = _candidate_models(installed, hardware, list(args.model))
    if not candidates:
        raise RuntimeError("Aucun modele agent local compatible ne peut etre qualifie.")

    results = []
    for candidate in candidates:
        runs = []
        for _index in range(repetitions):
            try:
                runs.append(_run_once(base_url, candidate["name"]))
            except Exception as exc:
                runs.append({"success": False, "error_type": type(exc).__name__})
        _unload(base_url, candidate["name"])
        successes = sum(1 for run in runs if run.get("success") is True)
        latencies = [float(run["duration_ms"]) for run in runs if run.get("duration_ms")]
        warm = latencies[1:] if len(latencies) > 1 else latencies
        results.append({
            "model": local_model_policy.canonical_name(candidate["name"]),
            "model_digest": candidate["digest"],
            "size_bytes": candidate["size_bytes"],
            "capabilities": candidate["capabilities"],
            "status": "qualified" if successes == repetitions else "failed",
            "qualified_roles": ["agent"] if successes == repetitions else [],
            "repetitions": repetitions,
            "success_rate": successes / repetitions,
            "cold_latency_ms": latencies[0] if latencies else None,
            "median_warm_latency_ms": round(statistics.median(warm), 1) if warm else None,
            "runs": runs,
        })

    qualified = [item for item in results if item["status"] == "qualified"]
    qualified.sort(key=lambda item: (float(item["median_warm_latency_ms"]), int(item["size_bytes"])))
    payload = {
        "schema": qualification.SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "machine_key": qualification.machine_key(hardware),
        "hardware": {key: hardware.get(key) for key in ("vendor", "gpu", "driver_version", "vram_gb", "ram_gb")},
        "ollama_version": ollama_version,
        "context_tokens": 8192,
        "repetitions": repetitions,
        "candidates": results,
        "winner_by_role": {"agent": qualified[0]["model"]} if qualified else {},
    }
    _atomic_write(output, payload)
    print(json.dumps({"output": str(output), "winner_by_role": payload["winner_by_role"], "candidates": results}, ensure_ascii=False))
    return 0 if qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
