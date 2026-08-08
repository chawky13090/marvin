"""Crée, vérifie ou libère le verrou LLM d'une campagne Forge Windows."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PROFILE = ROOT / "data" / "install" / "ollama-context-profile.json"
sys.path.insert(0, str(BACKEND))

import forge_runtime_lock  # noqa: E402


def _request_json(url: str, *, timeout: float = 8) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return payload if isinstance(payload, dict) else {}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_profile(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Profil Ollama certifié illisible.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "marvin.ollama-context-profile/1.1"
        or payload.get("status") != "verified"
        or not isinstance(payload.get("selected"), dict)
    ):
        raise ValueError("Profil Ollama 1.1 vérifié requis.")
    return payload


def _installed_digest(tags: dict[str, Any], model: str) -> str:
    expected = model.removesuffix(":latest")
    for item in tags.get("models") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").removesuffix(":latest")
        if name == expected:
            return str(item.get("digest") or "")
    return ""


def _runtime_observation(base_url: str, model: str) -> dict[str, Any]:
    version = str(_request_json(f"{base_url}/api/version").get("version") or "")
    tags = _request_json(f"{base_url}/api/tags")
    loaded = _request_json(f"{base_url}/api/ps").get("models") or []
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
    return {
        "model_digest": _installed_digest(tags, model),
        "ollama_version": version,
        "loaded_context_tokens": int(observed.get("context_length") or 0),
    }


def create_lock(args: argparse.Namespace) -> dict[str, Any]:
    profile_path = Path(args.profile).resolve()
    profile = _read_profile(profile_path)
    model = str(profile.get("model") or "")
    selected = profile["selected"]
    observation = _runtime_observation(args.ollama_url.rstrip("/"), model)
    if observation["model_digest"] != str(profile.get("model_digest") or ""):
        raise ValueError("Le digest installé ne correspond plus au profil certifié.")
    if observation["ollama_version"] != str(profile.get("ollama_version") or ""):
        raise ValueError("La version Ollama ne correspond plus au profil certifié.")
    campaign_id = forge_runtime_lock.validate_campaign_id(args.campaign_id)
    now = datetime.now(UTC)
    payload = {
        "schema": forge_runtime_lock.SCHEMA,
        "status": "active",
        "campaign_id": campaign_id,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=args.valid_hours)).isoformat(),
        "dynamic_routing_allowed": False,
        "profile_path_scope": "machine_local_not_portable",
        "profile_sha256": forge_runtime_lock.file_sha256(profile_path),
        "runtime": {
            "model": model,
            "model_digest": observation["model_digest"],
            "ollama_version": observation["ollama_version"],
            "context_tokens": int(selected.get("context_tokens") or 0),
            "kv_cache_type": str(selected.get("kv_cache_type") or ""),
            "flash_attention": 1,
            "parallel": int(selected.get("parallel") or 1),
            "temperature": args.temperature,
            "seed": args.seed,
        },
        "validation": {
            "required_before_every_run": True,
            "loaded_context_must_match_when_model_is_resident": True,
            "interrupted_run_must_be_discarded": True,
        },
    }
    output = forge_runtime_lock.allowed_lock_path(
        args.output
        or ROOT / "data" / "forge" / "runtime-locks" / f"{campaign_id}.json",
        ROOT,
    )
    _atomic_write(output, payload)
    return {
        "status": "created",
        "lock": str(output),
        "activate": [
            f'$env:MARVIN_FORGE_RUNTIME_LOCK="{output}"',
            f'$env:OLLAMA_KV_CACHE_TYPE="{payload["runtime"]["kv_cache_type"]}"',
            f'$env:OLLAMA_FLASH_ATTENTION="{payload["runtime"]["flash_attention"]}"',
            f'$env:OLLAMA_NUM_PARALLEL="{payload["runtime"]["parallel"]}"',
        ],
    }


def verify_lock(args: argparse.Namespace) -> dict[str, Any]:
    path = forge_runtime_lock.allowed_lock_path(args.lock, ROOT)
    payload = json.loads(path.read_text(encoding="utf-8"))
    runtime = payload.get("runtime") if isinstance(payload, dict) else {}
    model = str((runtime or {}).get("model") or "")
    profile_path = Path(args.profile).resolve()
    profile_hash = forge_runtime_lock.file_sha256(profile_path) if profile_path.is_file() else ""
    observation = _runtime_observation(args.ollama_url.rstrip("/"), model)
    errors = forge_runtime_lock.validate_lock_payload(
        payload,
        model=model,
        model_digest=observation["model_digest"],
        ollama_version=observation["ollama_version"],
        context_tokens=int((runtime or {}).get("context_tokens") or 0),
        kv_cache_type=os.getenv("OLLAMA_KV_CACHE_TYPE", ""),
        flash_attention=int(os.getenv("OLLAMA_FLASH_ATTENTION", "0") or 0),
        parallel=int(os.getenv("OLLAMA_NUM_PARALLEL", "0") or 0),
        profile_sha256=profile_hash,
    )
    loaded_context = int(observation.get("loaded_context_tokens") or 0)
    if loaded_context and loaded_context != int((runtime or {}).get("context_tokens") or 0):
        errors.append("loaded_context_drift")
    if errors:
        raise forge_runtime_lock.ForgeRuntimeDriftError(",".join(sorted(set(errors))))
    return {"status": "verified", "lock": str(path), "model_loaded": bool(loaded_context)}


def release_lock(args: argparse.Namespace) -> dict[str, Any]:
    path = forge_runtime_lock.allowed_lock_path(args.lock, ROOT)
    if not path.exists():
        return {"status": "already_absent", "lock": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != forge_runtime_lock.SCHEMA:
        raise ValueError("Le fichier n'est pas un verrou Forge reconnu.")
    payload["status"] = "released"
    payload["released_at"] = datetime.now(UTC).isoformat()
    _atomic_write(path, payload)
    return {"status": "released", "lock": str(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--campaign-id", required=True)
    create.add_argument("--output")
    create.add_argument("--profile", default=str(PROFILE))
    create.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    create.add_argument("--valid-hours", type=int, choices=range(1, 169), default=24)
    create.add_argument("--temperature", type=float, default=0.1)
    create.add_argument("--seed", type=int, default=0)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--lock", required=True)
    verify.add_argument("--profile", default=str(PROFILE))
    verify.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    release = subparsers.add_parser("release")
    release.add_argument("--lock", required=True)
    args = parser.parse_args()
    result = (
        create_lock(args)
        if args.action == "create"
        else (verify_lock(args) if args.action == "verify" else release_lock(args))
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, forge_runtime_lock.ForgeRuntimeDriftError) as exc:
        print(f"Verrou Forge refusé : {exc}", file=sys.stderr)
        raise SystemExit(2)
