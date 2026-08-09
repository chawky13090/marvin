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


def _post_json(url: str, payload: dict[str, Any], *, timeout: float = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    return result if isinstance(result, dict) else {}


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


def _provider_context(show: dict[str, Any]) -> int:
    model_info = show.get("model_info") if isinstance(show, dict) else None
    values = [
        int(value)
        for key, value in (model_info or {}).items()
        if str(key).endswith(".context_length")
        and isinstance(value, (int, float))
        and 0 < int(value) <= 10_000_000
    ]
    return max(values, default=0)


def _is_cloud_model(model: str) -> bool:
    normalized = str(model or "").strip().casefold()
    return normalized.endswith(":cloud") or normalized.endswith("-cloud")


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
    show = _post_json(f"{base_url}/api/show", {"model": model, "verbose": False})
    return {
        "model_digest": _installed_digest(tags, model),
        "ollama_version": version,
        "loaded_context_tokens": int(observed.get("context_length") or 0),
        "provider_declared_context_tokens": _provider_context(show),
    }


def _cloud_evidence(path: Path, model: str) -> dict[str, Any]:
    allowed = forge_runtime_lock.allowed_cloud_evidence_path(path, ROOT)
    try:
        payload = json.loads(allowed.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Preuve comportementale Cloud illisible.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Preuve comportementale Cloud invalide.")
    valid = (
        payload.get("schema") == "marvin.ollama-cloud-context-behavior/1.0"
        and str(payload.get("model") or "") == model
        and payload.get("status") == "verified_at_tested_depth"
        and payload.get("client_context_override") is None
        and payload.get("sentinel_retrieved") is True
        and int(payload.get("observed_prompt_tokens") or 0)
        >= int(payload.get("minimum_prompt_tokens") or 0)
        >= 32_768
        and payload.get("provider_maximum_proven") is False
    )
    if not valid:
        raise ValueError("Preuve comportementale Cloud non conforme au contrat Forge.")
    return {
        "path": allowed,
        "sha256": forge_runtime_lock.file_sha256(allowed),
        "observed_prompt_tokens": int(payload["observed_prompt_tokens"]),
        "minimum_prompt_tokens": int(payload["minimum_prompt_tokens"]),
    }


def create_lock(args: argparse.Namespace) -> dict[str, Any]:
    profile_path = Path(args.profile).resolve()
    requested_provider = str(args.provider or "auto")
    profile: dict[str, Any] | None = None
    if requested_provider == "cloud" or (args.model and _is_cloud_model(args.model)):
        provider = "cloud"
        model = str(args.model or "").strip()
        selected: dict[str, Any] = {}
        if not _is_cloud_model(model):
            raise ValueError("Un verrou Cloud exige un tag Ollama Cloud exact.")
    else:
        profile = _read_profile(profile_path)
        model = str(profile.get("model") or "")
        provider = "cloud" if _is_cloud_model(model) else "local"
        selected = profile["selected"]
    if requested_provider not in {"auto", provider}:
        raise ValueError("Le fournisseur demandé ne correspond pas au modèle exact.")
    observation = _runtime_observation(args.ollama_url.rstrip("/"), model)
    if not observation["model_digest"]:
        raise ValueError("Le modèle exact n'est plus présent dans l'inventaire Ollama.")
    if provider == "local" and observation["model_digest"] != str((profile or {}).get("model_digest") or ""):
        raise ValueError("Le digest installé ne correspond plus au profil certifié.")
    if provider == "local" and observation["ollama_version"] != str((profile or {}).get("ollama_version") or ""):
        raise ValueError("La version Ollama ne correspond plus au profil certifié.")
    cloud_evidence = None
    if provider == "cloud":
        if observation["provider_declared_context_tokens"] < 32_768:
            raise ValueError("La capacité Cloud déclarée est sous le plancher Forge.")
        if not args.cloud_evidence:
            raise ValueError("Une preuve comportementale Cloud est obligatoire.")
        cloud_evidence = _cloud_evidence(Path(args.cloud_evidence).resolve(), model)
    campaign_id = forge_runtime_lock.validate_campaign_id(args.campaign_id)
    now = datetime.now(UTC)
    payload = {
        "schema": forge_runtime_lock.SCHEMA,
        "status": "active",
        "campaign_id": campaign_id,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=args.valid_hours)).isoformat(),
        "dynamic_routing_allowed": False,
        "profile_path_scope": (
            "cloud_not_applicable" if provider == "cloud" else "machine_local_not_portable"
        ),
        "profile_sha256": (
            "" if provider == "cloud" else forge_runtime_lock.file_sha256(profile_path)
        ),
        "runtime": {
            "provider": provider,
            "model": model,
            "model_digest": observation["model_digest"],
            "ollama_version": observation["ollama_version"],
            "context_tokens": (
                None if provider == "cloud" else int(selected.get("context_tokens") or 0)
            ),
            "provider_declared_context_tokens": (
                int(observation["provider_declared_context_tokens"])
                if provider == "cloud"
                else None
            ),
            "client_context_override": False if provider == "cloud" else None,
            "cloud_runtime_allocation": "unavailable" if provider == "cloud" else None,
            "kv_cache_type": "" if provider == "cloud" else str(selected.get("kv_cache_type") or ""),
            "flash_attention": None if provider == "cloud" else 1,
            "parallel": None if provider == "cloud" else int(selected.get("parallel") or 1),
            "temperature": args.temperature,
            "seed": args.seed,
        },
        "validation": {
            "required_before_every_run": True,
            "loaded_context_must_match_when_model_is_resident": True,
            "interrupted_run_must_be_discarded": True,
        },
    }
    if cloud_evidence is not None:
        payload.update(
            {
                "cloud_evidence_path": cloud_evidence["path"].relative_to(ROOT).as_posix(),
                "cloud_evidence_sha256": cloud_evidence["sha256"],
                "cloud_behavioral_retention": {
                    "status": "verified_at_tested_depth",
                    "observed_prompt_tokens": cloud_evidence["observed_prompt_tokens"],
                    "minimum_prompt_tokens": cloud_evidence["minimum_prompt_tokens"],
                    "provider_maximum_proven": False,
                },
            }
        )
    output = forge_runtime_lock.allowed_lock_path(
        args.output
        or ROOT / "data" / "forge" / "runtime-locks" / f"{campaign_id}.json",
        ROOT,
    )
    _atomic_write(output, payload)
    activation = [f'$env:MARVIN_FORGE_RUNTIME_LOCK="{output}"']
    if provider == "local":
        activation.extend(
            [
                f'$env:OLLAMA_KV_CACHE_TYPE="{payload["runtime"]["kv_cache_type"]}"',
                f'$env:OLLAMA_FLASH_ATTENTION="{payload["runtime"]["flash_attention"]}"',
                f'$env:OLLAMA_NUM_PARALLEL="{payload["runtime"]["parallel"]}"',
            ]
        )
    return {
        "status": "created",
        "lock": str(output),
        "provider": provider,
        "activate": activation,
    }


def verify_lock(args: argparse.Namespace) -> dict[str, Any]:
    path = forge_runtime_lock.allowed_lock_path(args.lock, ROOT)
    payload = json.loads(path.read_text(encoding="utf-8"))
    runtime = payload.get("runtime") if isinstance(payload, dict) else {}
    model = str((runtime or {}).get("model") or "")
    provider = str((runtime or {}).get("provider") or "local")
    profile_path = Path(args.profile).resolve()
    profile_hash = (
        forge_runtime_lock.file_sha256(profile_path)
        if provider == "local" and profile_path.is_file()
        else ""
    )
    observation = _runtime_observation(args.ollama_url.rstrip("/"), model)
    cloud_evidence_hash = forge_runtime_lock.cloud_evidence_hash(payload, ROOT)
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
        provider=provider,
        provider_declared_context_tokens=int(
            observation.get("provider_declared_context_tokens") or 0
        ),
        cloud_evidence_sha256=cloud_evidence_hash,
    )
    loaded_context = int(observation.get("loaded_context_tokens") or 0)
    if provider == "local" and loaded_context and loaded_context != int((runtime or {}).get("context_tokens") or 0):
        errors.append("loaded_context_drift")
    if errors:
        raise forge_runtime_lock.ForgeRuntimeDriftError(",".join(sorted(set(errors))))
    return {
        "status": "verified",
        "lock": str(path),
        "provider": provider,
        "model_loaded": bool(loaded_context) if provider == "local" else None,
    }


def release_lock(args: argparse.Namespace) -> dict[str, Any]:
    path = forge_runtime_lock.allowed_lock_path(args.lock, ROOT)
    if not path.exists():
        return {"status": "already_absent", "lock": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema") not in forge_runtime_lock.RELEASABLE_SCHEMAS
    ):
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
    create.add_argument("--provider", choices=("auto", "local", "cloud"), default="auto")
    create.add_argument("--model")
    create.add_argument("--cloud-evidence")
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
