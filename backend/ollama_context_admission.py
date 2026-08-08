"""Admission locale de contexte Ollama aux frontières de mission.

Le contrôleur réévalue le modèle exact, le runtime et la pression mémoire avant
un tour. La décision est ensuite immuable pour l'identifiant de mission afin de
ne jamais changer de fenêtre au milieu d'un raisonnement. Les modèles Cloud ne
reçoivent volontairement aucune option ``num_ctx``.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

import auto_config
import forge_runtime_lock
import ollama_context_policy
from config import DATA_DIR, OLLAMA_URL, PROJECT_DIR
from structured_logging import StructuredJsonlStore


PROFILE_SCHEMA = "marvin.ollama-context-profile/1.1"
BOOTSTRAP_CONTEXT_TOKENS = 8_192
GIB = 1024**3


def _canonical_model(name: str) -> str:
    normalized = str(name or "").strip()
    return normalized[: -len(":latest")] if normalized.endswith(":latest") else normalized


def _is_cloud_model(name: str) -> bool:
    normalized = str(name or "").strip().casefold()
    return normalized.endswith(":cloud") or normalized.endswith("-cloud")


def _environment_int(name: str) -> int:
    try:
        return int(os.getenv(name, "0") or 0)
    except ValueError:
        return 0


def _machine_fingerprint(hardware: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor": str(hardware.get("vendor") or "unknown"),
        "gpu": str(hardware.get("gpu") or "unknown"),
        "driver_version": str(hardware.get("driver_version") or "unknown"),
        "vram_gb": round(float(hardware.get("vram_gb") or 0), 1),
        "ram_gb": round(float(hardware.get("ram_gb") or 0), 1),
    }


@dataclass(frozen=True, slots=True)
class ContextAdmission:
    status: str
    model: str
    context_tokens: int | None
    reason: str
    profile_verified: bool
    forge_locked: bool = False
    available_ram_bytes: int | None = None
    co_resident_model_count: int = 0

    def request_options(self) -> dict[str, int]:
        if _is_cloud_model(self.model) or self.context_tokens is None:
            return {}
        return {"num_ctx": int(self.context_tokens)}

    def public_event(self) -> dict[str, Any]:
        return {
            "type": "context_admission",
            "status": self.status,
            "contextTokens": self.context_tokens,
            "reason": self.reason,
            "forgeLocked": self.forge_locked,
        }


class ContextAdmissionController:
    """Contrôleur processus avec stabilité par mission et hystérésis d'upgrade."""

    def __init__(
        self,
        *,
        profile_path: Path | None = None,
        hardware_detector: Any = auto_config.detect_hardware,
        log_store: StructuredJsonlStore | None = None,
    ) -> None:
        self.profile_path = (
            profile_path or DATA_DIR / "install" / "ollama-context-profile.json"
        ).resolve()
        self.hardware_detector = hardware_detector
        self._mission_decisions: dict[str, ContextAdmission] = {}
        self._last_by_model: dict[str, ContextAdmission] = {}
        self._lock = threading.RLock()
        self._log_store = log_store or StructuredJsonlStore.from_environment(
            DATA_DIR / "logs" / "ollama-context-admission.jsonl",
            component="ollama_context_admission",
            prefix="OLLAMA_ADMISSION",
            default_retention_days=30,
        )

    def _read_profile(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _remember(self, mission_id: str, decision: ContextAdmission) -> ContextAdmission:
        with self._lock:
            if len(self._mission_decisions) >= 256:
                self._mission_decisions.pop(next(iter(self._mission_decisions)))
            self._mission_decisions[mission_id] = decision
            self._last_by_model[_canonical_model(decision.model)] = decision
        self._log_store.write(
            "ollama.context.admission",
            severity="ERROR" if decision.status == "blocked" else "INFO",
            outcome=(
                "failure"
                if decision.status == "blocked"
                else ("degraded" if decision.status == "degraded" else "success")
            ),
            trace_id=mission_id,
            attributes=asdict(decision),
        )
        return decision

    @staticmethod
    def _installed_model(tags: dict[str, Any], model: str) -> dict[str, Any] | None:
        expected = _canonical_model(model)
        models = tags.get("models") if isinstance(tags, dict) else None
        if not isinstance(models, list):
            return None
        return next(
            (
                item
                for item in models
                if isinstance(item, dict)
                and _canonical_model(str(item.get("name") or item.get("model") or ""))
                == expected
            ),
            None,
        )

    @staticmethod
    def _loaded_models(ps_payload: dict[str, Any]) -> list[dict[str, Any]]:
        models = ps_payload.get("models") if isinstance(ps_payload, dict) else None
        return [item for item in models or [] if isinstance(item, dict)]

    async def admit(
        self,
        model: str,
        *,
        mission_id: str,
        ollama_url: str = OLLAMA_URL,
        client: Any | None = None,
    ) -> ContextAdmission:
        stable_id = str(mission_id or "").strip()[:128] or "anonymous-mission"
        with self._lock:
            cached = self._mission_decisions.get(stable_id)
        if cached is not None:
            return cached
        if _is_cloud_model(model):
            return self._remember(
                stable_id,
                ContextAdmission(
                    status="cloud_provider_maximum",
                    model=model,
                    context_tokens=None,
                    reason="cloud_client_override_absent",
                    profile_verified=False,
                ),
            )

        owns_client = client is None
        http_client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0)
        )
        base_url = ollama_url.rstrip("/")
        try:
            version_response, tags_response, ps_response = await asyncio.gather(
                http_client.get(f"{base_url}/api/version"),
                http_client.get(f"{base_url}/api/tags"),
                http_client.get(f"{base_url}/api/ps"),
            )
            for response in (version_response, tags_response, ps_response):
                response.raise_for_status()
            version = str(version_response.json().get("version") or "")
            tags = tags_response.json()
            loaded = self._loaded_models(ps_response.json())
        except Exception:
            return self._remember(
                stable_id,
                ContextAdmission(
                    status="degraded",
                    model=model,
                    context_tokens=BOOTSTRAP_CONTEXT_TOKENS,
                    reason="runtime_inspection_unavailable",
                    profile_verified=False,
                ),
            )
        finally:
            if owns_client:
                await http_client.aclose()

        installed = self._installed_model(tags, model)
        digest = str((installed or {}).get("digest") or "")
        profile = self._read_profile()
        hardware = self.hardware_detector()
        available_ram = int(float(hardware.get("ram_available_gb") or 0) * GIB)
        co_resident = [
            item
            for item in loaded
            if _canonical_model(str(item.get("name") or item.get("model") or ""))
            != _canonical_model(model)
        ]

        active_lock = forge_runtime_lock.load_active_lock(PROJECT_DIR)
        if active_lock is not None:
            _lock_path, lock_payload = active_lock
            runtime = lock_payload.get("runtime") if isinstance(lock_payload, dict) else {}
            profile_hash = (
                forge_runtime_lock.file_sha256(self.profile_path)
                if self.profile_path.is_file()
                else ""
            )
            errors = forge_runtime_lock.validate_lock_payload(
                lock_payload,
                model=model,
                model_digest=digest,
                ollama_version=version,
                context_tokens=int((runtime or {}).get("context_tokens") or 0),
                kv_cache_type=os.getenv("OLLAMA_KV_CACHE_TYPE", ""),
                flash_attention=_environment_int("OLLAMA_FLASH_ATTENTION"),
                parallel=_environment_int("OLLAMA_NUM_PARALLEL"),
                profile_sha256=profile_hash,
            )
            if errors:
                return self._remember(
                    stable_id,
                    ContextAdmission(
                        status="blocked",
                        model=model,
                        context_tokens=None,
                        reason=errors[0],
                        profile_verified=False,
                        forge_locked=True,
                        available_ram_bytes=available_ram,
                        co_resident_model_count=len(co_resident),
                    ),
                )
            return self._remember(
                stable_id,
                ContextAdmission(
                    status="admitted",
                    model=model,
                    context_tokens=int(runtime["context_tokens"]),
                    reason="forge_runtime_lock_verified",
                    profile_verified=True,
                    forge_locked=True,
                    available_ram_bytes=available_ram,
                    co_resident_model_count=len(co_resident),
                ),
            )

        machine = _machine_fingerprint(hardware)
        invalid_reason = "verified_profile_missing"
        if isinstance(profile, dict):
            if profile.get("schema") != PROFILE_SCHEMA:
                invalid_reason = "profile_schema_stale"
            elif profile.get("status") != "verified":
                invalid_reason = "profile_not_verified"
            elif profile.get("machine_key") != ollama_context_policy.machine_profile_key(machine):
                invalid_reason = "machine_or_driver_drift"
            elif _canonical_model(str(profile.get("model") or "")) != _canonical_model(model):
                invalid_reason = "model_tag_drift"
            elif not installed:
                invalid_reason = "exact_model_not_installed"
            elif not digest or digest != str(profile.get("model_digest") or ""):
                invalid_reason = "model_digest_drift"
            elif version != str(profile.get("ollama_version") or ""):
                invalid_reason = "ollama_version_drift"
            elif not isinstance(profile.get("selected"), dict):
                invalid_reason = "profile_selection_missing"
            else:
                invalid_reason = ""
        if invalid_reason:
            return self._remember(
                stable_id,
                ContextAdmission(
                    status="degraded",
                    model=model,
                    context_tokens=BOOTSTRAP_CONTEXT_TOKENS,
                    reason=invalid_reason,
                    profile_verified=False,
                    available_ram_bytes=available_ram,
                    co_resident_model_count=len(co_resident),
                ),
            )

        selected = dict(profile["selected"])
        verified_candidates = [
            item
            for item in profile.get("verifications") or []
            if isinstance(item, dict)
            and item.get("status") == "verified"
            and item.get("kv_cache_type") == selected.get("kv_cache_type")
        ]
        if selected.get("status") == "verified":
            verified_candidates.append(selected)
        unique: dict[int, dict[str, Any]] = {}
        for item in verified_candidates:
            tokens = int(item.get("context_tokens") or 0)
            if BOOTSTRAP_CONTEXT_TOKENS <= tokens <= 1_048_576:
                unique[tokens] = item

        same_loaded = next(
            (
                item
                for item in loaded
                if _canonical_model(str(item.get("name") or item.get("model") or ""))
                == _canonical_model(model)
            ),
            None,
        )
        reclaimable = int((same_loaded or {}).get("size") or 0)
        effective_available = available_ram + reclaimable
        host_reserve = max(GIB, int(float(hardware.get("ram_gb") or 0) * GIB * 0.05))
        with self._lock:
            previous = self._last_by_model.get(_canonical_model(model))
        admitted: dict[str, Any] | None = None
        for tokens, candidate in sorted(unique.items(), reverse=True):
            projected = int(candidate.get("projected_resident_bytes") or 0)
            if projected <= 0:
                continue
            upgrading = previous is not None and tokens > int(previous.context_tokens or 0)
            headroom = 1.15 if upgrading else 1.05
            if effective_available >= int(projected * headroom) + host_reserve:
                admitted = candidate
                break
        if admitted is None:
            return self._remember(
                stable_id,
                ContextAdmission(
                    status="degraded",
                    model=model,
                    context_tokens=BOOTSTRAP_CONTEXT_TOKENS,
                    reason="runtime_memory_pressure",
                    profile_verified=True,
                    available_ram_bytes=available_ram,
                    co_resident_model_count=len(co_resident),
                ),
            )
        return self._remember(
            stable_id,
            ContextAdmission(
                status="admitted",
                model=model,
                context_tokens=int(admitted["context_tokens"]),
                reason="exact_profile_and_runtime_admitted",
                profile_verified=True,
                available_ram_bytes=available_ram,
                co_resident_model_count=len(co_resident),
            ),
        )


_CONTROLLER = ContextAdmissionController()


async def admit_local_context(
    model: str,
    *,
    mission_id: str,
    ollama_url: str = OLLAMA_URL,
) -> ContextAdmission:
    return await _CONTROLLER.admit(
        model,
        mission_id=mission_id,
        ollama_url=ollama_url,
    )
