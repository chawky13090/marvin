"""Verrou reproductible du runtime LLM pour les campagnes Marvin Forge.

Le verrou est volontairement distinct du plan de benchmark. Le plan décrit la
méthode; ce module empêche réellement le modèle, son digest, Ollama, le contexte
ou le cache KV de dériver pendant une campagne.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA = "marvin.forge-runtime-lock/1.1"
RELEASABLE_SCHEMAS = {"marvin.forge-runtime-lock/1.0", SCHEMA}
_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_PROVIDERS = {"local", "cloud"}


class ForgeRuntimeDriftError(RuntimeError):
    """Le runtime observé ne correspond plus au manifeste pré-enregistré."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def validate_campaign_id(value: str) -> str:
    campaign_id = str(value or "").strip()
    if not _CAMPAIGN_ID.fullmatch(campaign_id):
        raise ValueError("Identifiant de campagne Forge invalide.")
    return campaign_id


def validate_lock_payload(
    payload: dict[str, Any],
    *,
    model: str,
    model_digest: str,
    ollama_version: str,
    context_tokens: int,
    kv_cache_type: str,
    flash_attention: int,
    parallel: int,
    profile_sha256: str,
    provider: str | None = None,
    provider_declared_context_tokens: int = 0,
    cloud_evidence_sha256: str = "",
    now: datetime | None = None,
) -> list[str]:
    """Retourne des codes de dérive stables, sans contenu ni secret."""

    errors: list[str] = []
    if payload.get("schema") != SCHEMA or payload.get("status") != "active":
        errors.append("lock_schema_or_status_invalid")
    if payload.get("dynamic_routing_allowed") is not False:
        errors.append("dynamic_routing_not_disabled")
    expected = payload.get("runtime")
    if not isinstance(expected, dict):
        return [*errors, "runtime_contract_missing"]
    expected_provider = str(expected.get("provider") or "local").casefold()
    actual_provider = str(provider or expected_provider).casefold()
    if expected_provider not in _PROVIDERS:
        errors.append("runtime_provider_invalid")
    comparisons = {
        "provider_drift": (expected_provider, actual_provider),
        "model_drift": (str(expected.get("model") or ""), str(model or "")),
        "model_digest_drift": (
            str(expected.get("model_digest") or ""),
            str(model_digest or ""),
        ),
        "ollama_version_drift": (
            str(expected.get("ollama_version") or ""),
            str(ollama_version or ""),
        ),
    }
    if expected_provider == "cloud":
        comparisons.update(
            {
                "provider_context_drift": (
                    int(expected.get("provider_declared_context_tokens") or 0),
                    int(provider_declared_context_tokens or 0),
                ),
                "cloud_evidence_drift": (
                    str(payload.get("cloud_evidence_sha256") or ""),
                    str(cloud_evidence_sha256 or ""),
                ),
            }
        )
        if expected.get("client_context_override") is not False:
            errors.append("cloud_client_context_override_present")
        if expected.get("cloud_runtime_allocation") != "unavailable":
            errors.append("cloud_runtime_allocation_overstated")
        if int(expected.get("provider_declared_context_tokens") or 0) <= 0:
            errors.append("provider_context_missing")
        if not str(payload.get("cloud_evidence_sha256") or ""):
            errors.append("cloud_evidence_missing")
    else:
        comparisons.update(
            {
                "context_drift": (
                    int(expected.get("context_tokens") or 0),
                    int(context_tokens or 0),
                ),
                "kv_cache_drift": (
                    str(expected.get("kv_cache_type") or ""),
                    str(kv_cache_type or ""),
                ),
                "parallel_drift": (
                    int(expected.get("parallel") or 0),
                    int(parallel or 0),
                ),
                "flash_attention_drift": (
                    int(expected.get("flash_attention") or 0),
                    int(flash_attention or 0),
                ),
                "profile_drift": (
                    str(payload.get("profile_sha256") or ""),
                    str(profile_sha256 or ""),
                ),
            }
        )
    errors.extend(code for code, pair in comparisons.items() if pair[0] != pair[1])
    expires_at = parse_timestamp(payload.get("expires_at"))
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if expires_at is None or expires_at <= current:
        errors.append("lock_expired")
    return errors


def allowed_lock_path(raw_path: str | os.PathLike[str], root: Path) -> Path:
    """Refuse qu'une variable d'environnement fasse lire un fichier arbitraire."""

    path = Path(raw_path).resolve()
    allowed_roots = (
        (root / "data" / "forge" / "runtime-locks").resolve(),
        (root / "benchmarks" / "windows-operator" / "campaigns").resolve(),
    )
    if path.suffix.casefold() != ".json" or not any(
        path == allowed or allowed in path.parents for allowed in allowed_roots
    ):
        raise ValueError("Chemin de verrou Forge hors périmètre autorisé.")
    return path


def allowed_cloud_evidence_path(raw_path: str | os.PathLike[str], root: Path) -> Path:
    """Borne une preuve Cloud aux campagnes Forge versionnées/locales."""

    path = Path(raw_path).resolve()
    allowed = (root / "benchmarks" / "windows-operator" / "campaigns").resolve()
    if path.suffix.casefold() != ".json" or allowed not in path.parents:
        raise ValueError("Preuve Cloud Forge hors périmètre autorisé.")
    return path


def cloud_evidence_hash(payload: dict[str, Any], root: Path) -> str:
    """Retourne l'empreinte observée d'une preuve Cloud référencée par le lock."""

    raw_path = str(payload.get("cloud_evidence_path") or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    try:
        allowed = allowed_cloud_evidence_path(path, root)
    except ValueError:
        return ""
    return file_sha256(allowed) if allowed.is_file() else ""


def load_active_lock(root: Path) -> tuple[Path, dict[str, Any]] | None:
    raw_path = os.getenv("MARVIN_FORGE_RUNTIME_LOCK", "").strip()
    if not raw_path:
        return None
    path = allowed_lock_path(raw_path, root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForgeRuntimeDriftError("forge_runtime_lock_unreadable") from exc
    if not isinstance(payload, dict):
        raise ForgeRuntimeDriftError("forge_runtime_lock_invalid")
    return path, payload
