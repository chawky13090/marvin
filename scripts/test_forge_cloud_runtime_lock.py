"""Contrat du verrou Forge Cloud, sans appel réseau ni génération LLM."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPT = ROOT / "scripts" / "forge-runtime-lock.py"
sys.path.insert(0, str(BACKEND))

SPEC = importlib.util.spec_from_file_location("forge_runtime_lock_cli", SCRIPT)
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


def _args(root: Path, evidence: Path) -> argparse.Namespace:
    return argparse.Namespace(
        campaign_id="test-cloud-lock",
        output=str(root / "runtime-lock.json"),
        profile=str(ROOT / "data" / "install" / "unused.json"),
        ollama_url="http://127.0.0.1:11434",
        valid_hours=1,
        temperature=0.1,
        seed=0,
        provider="cloud",
        model="qwen3.5:397b-cloud",
        cloud_evidence=str(evidence),
    )


def main() -> int:
    campaign = ROOT / "benchmarks" / "windows-operator" / "campaigns" / ".test-cloud-lock"
    shutil.rmtree(campaign, ignore_errors=True)
    campaign.mkdir(parents=True)
    evidence = campaign / "retention.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": "marvin.ollama-cloud-context-behavior/1.0",
                "model": "qwen3.5:397b-cloud",
                "status": "verified_at_tested_depth",
                "client_context_override": None,
                "minimum_prompt_tokens": 32_768,
                "observed_prompt_tokens": 45_000,
                "sentinel_retrieved": True,
                "provider_maximum_proven": False,
            }
        ),
        encoding="utf-8",
    )
    observation = {
        "model_digest": "cloud-digest-1",
        "ollama_version": "0.32.6",
        "loaded_context_tokens": 0,
        "provider_declared_context_tokens": 262_144,
    }
    try:
        args = _args(campaign, evidence)
        with patch.object(CLI, "_runtime_observation", return_value=observation):
            created = CLI.create_lock(args)
        lock_path = Path(created["lock"])
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        runtime = payload["runtime"]
        assert created["provider"] == "cloud"
        assert len(created["activate"]) == 1
        assert runtime["model"] == "qwen3.5:397b-cloud"
        assert runtime["model_digest"] == "cloud-digest-1"
        assert runtime["provider_declared_context_tokens"] == 262_144
        assert runtime["client_context_override"] is False
        assert runtime["cloud_runtime_allocation"] == "unavailable"
        assert runtime["context_tokens"] is None

        verify = argparse.Namespace(
            lock=str(lock_path),
            profile=args.profile,
            ollama_url=args.ollama_url,
        )
        with patch.object(CLI, "_runtime_observation", return_value=observation):
            verified = CLI.verify_lock(verify)
        assert verified["status"] == "verified" and verified["provider"] == "cloud"

        evidence.write_text("{}", encoding="utf-8")
        with patch.object(CLI, "_runtime_observation", return_value=observation):
            try:
                CLI.verify_lock(verify)
            except CLI.forge_runtime_lock.ForgeRuntimeDriftError as exc:
                assert "cloud_evidence_drift" in str(exc)
            else:
                raise AssertionError("Une preuve Cloud modifiée doit invalider le verrou.")
    finally:
        shutil.rmtree(campaign, ignore_errors=True)
    print("Forge Cloud runtime lock OK - identité, capacité et preuve figées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
