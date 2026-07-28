"""Régressions du plan de modèles locaux utilisé pendant l'installation."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import local_model_policy
import plan_local_models


def main() -> int:
    hardware = {
        "vendor": "nvidia",
        "vram_gb": 4.0,
        "ram_gb": 16.0,
        "ram_available_gb": 10.0,
        "disk_free_bytes": 80 * local_model_policy.GIB,
    }
    plan = plan_local_models.build_plan(hardware, [])
    catalog_names = {
        item["name"] for item in local_model_policy.load_catalog()["entries"]
    }
    assert plan
    assert len(plan) == len(set(plan))
    assert set(plan) <= catalog_names
    assert all('"' not in model and "&" not in model for model in plan)

    installed = [
        {"name": model, "size_bytes": next(
            item["size_bytes"]
            for item in local_model_policy.load_catalog()["entries"]
            if item["name"] == model
        )}
        for model in plan
    ]
    assert plan_local_models.build_plan(hardware, installed) == []
    print("Plan modèles installation OK - dynamique, borné, idempotent et sûr pour la CLI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
