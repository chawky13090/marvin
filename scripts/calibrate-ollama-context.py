"""Calibre le contexte Ollama local par calcul puis vérification isolée.

Le script ne redémarre et ne modifie jamais le service Ollama de Marvin. Il lance
un serveur temporaire sur un port libre, vérifie un ou deux candidats, puis écrit
atomiquement un profil lié au matériel et au digest exact du modèle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_PROFILE = ROOT / "data" / "install" / "ollama-context-profile.json"
sys.path.insert(0, str(BACKEND))

import auto_config  # noqa: E402
import local_model_policy  # noqa: E402
import ollama_context_policy as context_policy  # noqa: E402


def _extract_final_answer(text: str) -> str:
    """Écarte une trace de réflexion Qwen3 avant de valider la réponse utile."""

    normalized = str(text or "").strip()
    if "</think>" in normalized.casefold():
        marker = normalized.casefold().rfind("</think>")
        normalized = normalized[marker + len("</think>") :].strip()
    return normalized


def _request_json(url: str, *, payload: dict[str, Any] | None = None, timeout: float = 10) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    return result if isinstance(result, dict) else {}


def _installed_models(base_url: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _request_json(f"{base_url}/api/tags").get("models", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name or name.endswith(":cloud") or name.endswith("-cloud"):
            continue
        result.append(
            {
                "name": name,
                "size_bytes": int(item.get("size") or 0),
                "digest": str(item.get("digest") or ""),
                "capabilities": list(item.get("capabilities") or []),
                "context_tokens": int((item.get("details") or {}).get("context_length") or 0),
            }
        )
    return result


def _select_model(models: list[dict[str, Any]], hardware: dict[str, Any], requested: str | None) -> dict[str, Any]:
    if requested:
        selected = local_model_policy.exact_installed_model(requested, models)
        if selected is None:
            raise ValueError(f"Modèle local exact absent : {requested}")
        return selected
    recommendation = local_model_policy.recommend(hardware, models)
    selected_name = recommendation.get("chosen", {}).get("agent")
    selected = local_model_policy.exact_installed_model(str(selected_name or ""), models)
    if selected is None:
        raise ValueError("Aucun modèle agent local compatible n'est installé.")
    return selected


def _machine_fingerprint(hardware: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor": str(hardware.get("vendor") or "unknown"),
        "gpu": str(hardware.get("gpu") or "unknown"),
        "vram_gb": round(float(hardware.get("vram_gb") or 0), 1),
        "ram_gb": round(float(hardware.get("ram_gb") or 0), 1),
    }


def _ollama_executable() -> str:
    found = shutil.which("ollama")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if local.is_file():
        return str(local)
    raise FileNotFoundError("ollama.exe introuvable")


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_ready(base_url: str, process: subprocess.Popen[Any], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Le serveur Ollama isolé s'est arrêté ({process.returncode}).")
        try:
            _request_json(f"{base_url}/api/version", timeout=1)
            return
        except (OSError, ValueError):
            time.sleep(0.25)
    raise TimeoutError("Le serveur Ollama isolé n'est pas devenu prêt.")


def _stop_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
            check=False,
            creationflags=0x08000000,
        )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _verify_candidate(
    model: str,
    candidate: dict[str, Any],
    *,
    repetitions: int,
) -> dict[str, Any]:
    port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update(
        {
            "OLLAMA_HOST": f"127.0.0.1:{port}",
            "OLLAMA_CONTEXT_LENGTH": str(candidate["context_tokens"]),
            "OLLAMA_KV_CACHE_TYPE": str(candidate["kv_cache_type"]),
            "OLLAMA_FLASH_ATTENTION": "1",
            "OLLAMA_NUM_PARALLEL": "1",
        }
    )
    creation_flags = 0x08000000 if os.name == "nt" else 0
    log_path = Path(tempfile.gettempdir()) / f"marvin-ollama-calibration-{port}.log"
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    runs: list[dict[str, Any]] = []
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(
                [_ollama_executable(), "serve"],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
            _wait_ready(base_url, process)
            for _ in range(repetitions):
                run_started = time.monotonic()
                response = _request_json(
                    f"{base_url}/api/generate",
                    payload={
                        "model": model,
                        "prompt": "Écris exactement CALIBRATION_OK et rien d'autre.",
                        "stream": False,
                        "think": False,
                        "keep_alive": "2m",
                        "options": {"temperature": 0, "num_predict": 256},
                    },
                    timeout=180,
                )
                text = str(response.get("response") or "").strip()
                final_answer = _extract_final_answer(text)
                runs.append(
                    {
                        "duration_ms": round((time.monotonic() - run_started) * 1000, 1),
                        "load_duration_ns": int(response.get("load_duration") or 0),
                        "prompt_eval_duration_ns": int(response.get("prompt_eval_duration") or 0),
                        "eval_duration_ns": int(response.get("eval_duration") or 0),
                        "output_contract_passed": final_answer.casefold() == "calibration_ok",
                        "final_answer_sha256": hashlib.sha256(
                            final_answer.encode("utf-8", errors="replace")
                        ).hexdigest(),
                    }
                )
            loaded = _request_json(f"{base_url}/api/ps").get("models", [])
            observed = next(
                (
                    item
                    for item in loaded
                    if isinstance(item, dict)
                    and str(item.get("name") or item.get("model") or "").removesuffix(":latest")
                    == model.removesuffix(":latest")
                ),
                {},
            )
            _request_json(
                f"{base_url}/api/generate",
                payload={"model": model, "keep_alive": 0},
                timeout=30,
            )
    finally:
        if process is not None:
            _stop_process_tree(process)
    size = int(observed.get("size") or 0)
    size_vram = int(observed.get("size_vram") or 0)
    allocated = int(observed.get("context_length") or 0)
    return {
        **candidate,
        "status": "verified" if allocated == int(candidate["context_tokens"]) and all(run["output_contract_passed"] for run in runs) else "failed",
        "allocated_context_tokens": allocated or None,
        "runtime_size_bytes": size or None,
        "runtime_size_vram_bytes": size_vram or None,
        "gpu_residency_ratio": round(size_vram / size, 4) if size and size_vram <= size else None,
        "flash_attention_requested": True,
        "parallel": 1,
        "runs": runs,
        "total_duration_ms": round((time.monotonic() - started) * 1000, 1),
        "temporary_log_scope": "os_temp_ephemeral_not_preserved",
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _candidate_score(item: dict[str, Any], minimum: int) -> tuple[int, int, int, float]:
    return (
        int(int(item.get("context_tokens") or 0) >= minimum),
        int(item.get("context_tokens") or 0),
        int(item.get("kv_cache_type") == "f16"),
        float(item.get("gpu_residency_ratio") or 0),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Tag local exact. Par défaut : rôle agent recommandé.")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--output", default=str(DEFAULT_PROFILE))
    parser.add_argument("--verify", action="store_true", help="Vérifie les candidats sur un serveur isolé.")
    parser.add_argument("--install-profile", action="store_true", help="Installe aussi le profil vérifié pour start.bat.")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--minimum-tokens", type=int)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10 or (args.minimum_tokens is not None and args.minimum_tokens < 8_192):
        parser.error("Paramètres de calibration hors limites.")

    base_url = args.ollama_url.rstrip("/")
    hardware = auto_config.detect_hardware()
    minimum_tokens = args.minimum_tokens or auto_config.context_objective_tokens(hardware)
    installed = _installed_models(base_url)
    model = _select_model(installed, hardware, args.model)
    show = _request_json(f"{base_url}/api/show", payload={"model": model["name"], "verbose": False})
    proposal = context_policy.propose_context_candidates(
        show,
        model_size_bytes=int(model["size_bytes"]),
        vram_budget_bytes=local_model_policy.memory_budget_bytes(hardware),
        ram_available_bytes=int(float(hardware.get("ram_available_gb") or hardware.get("ram_gb") or 0) * context_policy.GIB),
        requested_minimum=minimum_tokens,
        parallel=1,
    )
    verified = [
        _verify_candidate(model["name"], item, repetitions=args.repetitions)
        for item in proposal["candidates"]
    ] if args.verify else []
    passing = [item for item in verified if item["status"] == "verified"]
    selected = max(passing, key=lambda item: _candidate_score(item, minimum_tokens)) if passing else None
    fingerprint = _machine_fingerprint(hardware)
    profile = {
        "schema": "marvin.ollama-context-profile/1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "verified" if selected else "calculated_pending_verification",
        "machine": fingerprint,
        "machine_key": context_policy.machine_profile_key(fingerprint),
        "model": model["name"],
        "model_digest": model.get("digest") or None,
        "ollama_version": _request_json(f"{base_url}/api/version").get("version"),
        "proposal": proposal,
        "verifications": verified,
        "selected": selected,
        "cloud_policy": {
            "client_context_override": None,
            "provider_maximum_preserved": True,
            "runtime_allocation_observable": False,
        },
    }
    output = Path(args.output).resolve()
    allowed_roots = [(ROOT / "data" / "install").resolve(), (ROOT / "benchmarks" / "windows-operator" / "campaigns").resolve()]
    if not any(output == root or root in output.parents for root in allowed_roots) or output.suffix.casefold() != ".json":
        raise ValueError("La sortie doit rester dans data/install ou benchmarks/windows-operator/campaigns.")
    _atomic_write(output, profile)
    installed_profile = None
    if args.install_profile and selected:
        _atomic_write(DEFAULT_PROFILE, profile)
        installed_profile = str(DEFAULT_PROFILE)
    print(json.dumps({"output": str(output), "installed_profile": installed_profile, "status": profile["status"], "model": model["name"], "selected": selected}, ensure_ascii=False))
    return 0 if selected or not args.verify else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, context_policy.ContextPolicyError) as exc:
        print(f"Calibration Ollama impossible : {exc}", file=sys.stderr)
        raise SystemExit(2)
