"""Smoke test réel du calcul de contexte pour les modèles Ollama locaux installés."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import auto_config
import cloud_routing
import local_model_policy
import ollama_context_policy


def main() -> int:
    base_url = str(auto_config.OLLAMA_URL).rstrip("/")
    hardware = auto_config.detect_hardware()
    ram_bytes = int(
        float(hardware.get("ram_available_gb") or hardware.get("ram_gb") or 0)
        * ollama_context_policy.GIB
    )
    budget = local_model_policy.memory_budget_bytes(hardware)
    with httpx.Client(timeout=15) as client:
        response = client.get(f"{base_url}/api/tags")
        response.raise_for_status()
        models = response.json().get("models") or []
        checked = 0
        for model in models:
            name = str(model.get("name") or "")
            if not name or cloud_routing.is_cloud_model(name):
                continue
            show_response = client.post(
                f"{base_url}/api/show", json={"model": name, "verbose": False}
            )
            show_response.raise_for_status()
            show = show_response.json()
            capabilities = set(show.get("capabilities") or [])
            if "completion" not in capabilities:
                continue
            proposal = ollama_context_policy.propose_context_candidates(
                show,
                model_size_bytes=int(model.get("size") or 0),
                vram_budget_bytes=budget,
                ram_available_bytes=ram_bytes,
                requested_minimum=auto_config.context_objective_tokens(hardware),
                parallel=1,
            )
            if not proposal["candidates"]:
                raise AssertionError(f"Aucun candidat calculé pour {name}")
            shape = proposal["attention_shape"]
            print(
                f"OK {name}: namespace={shape['metadata_namespace']} "
                f"status={shape['status']} candidates={len(proposal['candidates'])}"
            )
            checked += 1
    if checked < 1:
        raise AssertionError("Aucun modèle local génératif n'a été vérifié.")
    print(f"Ollama local context matrix OK - {checked} modèles génératifs vérifiés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
