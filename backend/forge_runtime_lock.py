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


SCHEMA = "marvin.forge-runtime-lock/1.0"
_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


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
    comparisons = {
        "model_drift": (str(expected.get("model") or ""), str(model or "")),
        "model_digest_drift": (
            str(expected.get("model_digest") or ""),
            str(model_digest or ""),
        ),
        "ollama_version_drift": (
            str(expected.get("ollama_version") or ""),
            str(ollama_version or ""),
        ),
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
