"""Régressions de l'admission Ollama et du verrou Forge, sans charger de LLM."""

from __future__ import annotations

import asyncio
import httpx
import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import forge_runtime_lock
import ollama_context_admission as admission
import ollama_context_policy
from structured_logging import StructuredJsonlStore


HARDWARE = {
    "vendor": "nvidia",
    "gpu": "Test GPU",
    "driver_version": "999.1",
    "vram_gb": 8.0,
    "ram_gb": 32.0,
    "ram_available_gb": 12.0,
}


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(
        self,
        *,
        digest: str = "digest-1",
        cloud_digest: str = "cloud-digest-1",
        cloud_context: int = 262_144,
        loaded: list[dict] | None = None,
        transient_version_failures: int = 0,
    ) -> None:
        self.digest = digest
        self.cloud_digest = cloud_digest
        self.cloud_context = cloud_context
        self.loaded = loaded or []
        self.transient_version_failures = transient_version_failures
        self.calls = 0

    async def get(self, url: str) -> FakeResponse:
        self.calls += 1
        if url.endswith("/api/version"):
            if self.transient_version_failures:
                self.transient_version_failures -= 1
                raise httpx.ReadTimeout("transient test failure")
            return FakeResponse({"version": "0.32.5"})
        if url.endswith("/api/tags"):
            return FakeResponse(
                {
                    "models": [
                        {"name": "qwen3:4b", "digest": self.digest},
                        {
                            "name": "qwen3.5:397b-cloud",
                            "digest": self.cloud_digest,
                        },
                    ]
                }
            )
        if url.endswith("/api/ps"):
            return FakeResponse({"models": self.loaded})
        raise AssertionError(url)

    async def post(self, url: str, *, json: dict) -> FakeResponse:
        self.calls += 1
        if url.endswith("/api/show") and json.get("model") == "qwen3.5:397b-cloud":
            return FakeResponse(
                {"model_info": {"qwen3.5.context_length": self.cloud_context}}
            )
        raise AssertionError((url, json))


def _profile() -> dict:
    machine = admission._machine_fingerprint(HARDWARE)
    selected = {
        "status": "verified",
        "context_tokens": 32_768,
        "kv_cache_type": "q8_0",
        "projected_resident_bytes": 5 * admission.GIB,
        "parallel": 1,
    }
    return {
        "schema": admission.PROFILE_SCHEMA,
        "status": "verified",
        "machine_key": ollama_context_policy.machine_profile_key(machine),
        "model": "qwen3:4b",
        "model_digest": "digest-1",
        "ollama_version": "0.32.5",
        "selected": selected,
        "verifications": [selected],
    }


async def _run() -> None:
    previous_lock = os.environ.pop("MARVIN_FORGE_RUNTIME_LOCK", None)
    try:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            profile_path = temp_path / "profile.json"
            profile_path.write_text(json.dumps(_profile()), encoding="utf-8")
            store = StructuredJsonlStore(
                temp_path / "admission.jsonl",
                component="test",
                retention_days=1,
            )
            controller = admission.ContextAdmissionController(
                profile_path=profile_path,
                hardware_detector=lambda: dict(HARDWARE),
                log_store=store,
            )
            cloud_client = FakeClient()
            cloud = await controller.admit(
                "qwen3.5:397b-cloud",
                mission_id="cloud-1",
                client=cloud_client,
            )
            assert cloud.status == "cloud_provider_maximum"
            assert cloud.request_options() == {}
            assert cloud_client.calls == 0

            accepted = await controller.admit(
                "qwen3:4b", mission_id="local-1", client=FakeClient()
            )
            assert accepted.status == "admitted"
            assert accepted.request_options() == {"num_ctx": 32_768}

            # Une décision ne change jamais au milieu de la même mission.
            stable = await controller.admit(
                "qwen3:4b",
                mission_id="local-1",
                client=FakeClient(digest="digest-changed"),
            )
            assert stable == accepted

            digest_drift = await controller.admit(
                "qwen3:4b",
                mission_id="local-2",
                client=FakeClient(digest="digest-changed"),
            )
            assert digest_drift.status == "degraded"
            assert digest_drift.reason == "model_digest_drift"
            assert digest_drift.context_tokens == 8_192

            pressured_hardware = {**HARDWARE, "ram_available_gb": 1.5}
            pressured = admission.ContextAdmissionController(
                profile_path=profile_path,
                hardware_detector=lambda: pressured_hardware,
                log_store=store,
            )
            degraded = await pressured.admit(
                "qwen3:4b",
                mission_id="pressure-1",
                client=FakeClient(
                    loaded=[
                        {
                            "name": "nomic-embed-text:latest",
                            "size": 900_000_000,
                            "context_length": 2_048,
                        }
                    ]
                ),
            )
            assert degraded.status == "degraded"
            assert degraded.reason == "runtime_memory_pressure"
            assert degraded.co_resident_model_count == 1

            now = datetime.now(UTC)
            lock = {
                "schema": forge_runtime_lock.SCHEMA,
                "status": "active",
                "dynamic_routing_allowed": False,
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "profile_sha256": "profile-hash",
                "runtime": {
                    "model": "qwen3:4b",
                    "model_digest": "digest-1",
                    "ollama_version": "0.32.5",
                    "context_tokens": 32_768,
                    "kv_cache_type": "q8_0",
                    "flash_attention": 1,
                    "parallel": 1,
                },
            }
            assert not forge_runtime_lock.validate_lock_payload(
                lock,
                model="qwen3:4b",
                model_digest="digest-1",
                ollama_version="0.32.5",
                context_tokens=32_768,
                kv_cache_type="q8_0",
                flash_attention=1,
                parallel=1,
                profile_sha256="profile-hash",
                now=now,
            )
            errors = forge_runtime_lock.validate_lock_payload(
                lock,
                model="other:4b",
                model_digest="digest-1",
                ollama_version="0.32.5",
                context_tokens=32_768,
                kv_cache_type="q8_0",
                flash_attention=1,
                parallel=1,
                profile_sha256="profile-hash",
                now=now,
            )
            assert "model_drift" in errors

            lock["profile_sha256"] = forge_runtime_lock.file_sha256(profile_path)
            os.environ["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
            os.environ["OLLAMA_FLASH_ATTENTION"] = "1"
            os.environ["OLLAMA_NUM_PARALLEL"] = "1"
            locked_controller = admission.ContextAdmissionController(
                profile_path=profile_path,
                hardware_detector=lambda: dict(HARDWARE),
                log_store=store,
            )
            with patch.object(
                forge_runtime_lock,
                "load_active_lock",
                return_value=(temp_path / "lock.json", lock),
            ):
                locked = await locked_controller.admit(
                    "qwen3:4b", mission_id="locked-1", client=FakeClient()
                )
                assert locked.status == "admitted" and locked.forge_locked is True
                os.environ["OLLAMA_NUM_PARALLEL"] = "2"
                blocked = await locked_controller.admit(
                    "qwen3:4b", mission_id="locked-2", client=FakeClient()
                )
                assert blocked.status == "blocked"
                assert blocked.reason == "parallel_drift"

            cloud_lock = {
                "schema": forge_runtime_lock.SCHEMA,
                "status": "active",
                "dynamic_routing_allowed": False,
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "profile_sha256": "",
                "cloud_evidence_path": "benchmarks/windows-operator/campaigns/test/cloud.json",
                "cloud_evidence_sha256": "cloud-proof-hash",
                "runtime": {
                    "provider": "cloud",
                    "model": "qwen3.5:397b-cloud",
                    "model_digest": "cloud-digest-1",
                    "ollama_version": "0.32.5",
                    "context_tokens": None,
                    "provider_declared_context_tokens": 262_144,
                    "client_context_override": False,
                    "cloud_runtime_allocation": "unavailable",
                    "kv_cache_type": "",
                    "flash_attention": None,
                    "parallel": None,
                },
            }
            cloud_locked_controller = admission.ContextAdmissionController(
                profile_path=profile_path,
                hardware_detector=lambda: dict(HARDWARE),
                log_store=store,
            )
            with (
                patch.object(
                    forge_runtime_lock,
                    "load_active_lock",
                    return_value=(temp_path / "cloud-lock.json", cloud_lock),
                ),
                patch.object(
                    forge_runtime_lock,
                    "cloud_evidence_hash",
                    return_value="cloud-proof-hash",
                ),
            ):
                cloud_locked = await cloud_locked_controller.admit(
                    "qwen3.5:397b-cloud",
                    mission_id="cloud-locked-1",
                    client=FakeClient(),
                )
                assert cloud_locked.status == "cloud_provider_maximum"
                assert cloud_locked.forge_locked is True
                assert cloud_locked.request_options() == {}

                cloud_drift = await cloud_locked_controller.admit(
                    "qwen3.5:397b-cloud",
                    mission_id="cloud-locked-2",
                    client=FakeClient(cloud_context=131_072),
                )
                assert cloud_drift.status == "blocked"
                assert cloud_drift.reason == "provider_context_drift"

                cloud_retry = await cloud_locked_controller.admit(
                    "qwen3.5:397b-cloud",
                    mission_id="cloud-locked-retry",
                    client=FakeClient(transient_version_failures=1),
                )
                assert cloud_retry.status == "cloud_provider_maximum"
                assert cloud_retry.forge_locked is True

            records = store.recent(20)
            assert records
            encoded = json.dumps(records)
            assert "digest-1" not in encoded
    finally:
        for variable in (
            "OLLAMA_KV_CACHE_TYPE",
            "OLLAMA_FLASH_ATTENTION",
            "OLLAMA_NUM_PARALLEL",
        ):
            os.environ.pop(variable, None)
        if previous_lock is not None:
            os.environ["MARVIN_FORGE_RUNTIME_LOCK"] = previous_lock


def main() -> int:
    asyncio.run(_run())
    print("Ollama context admission OK - modèle exact, pression, stabilité et verrou Forge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
