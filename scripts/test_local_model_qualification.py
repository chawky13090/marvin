"""Regressions de la qualification locale liee au materiel et au digest."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import local_model_qualification as qualification


HARDWARE = {
    "vendor": "nvidia", "gpu": "Test GPU", "driver_version": "1.0",
    "vram_gb": 4.0, "ram_gb": 32.0,
}


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "qualification.json"
        payload = {
            "schema": qualification.SCHEMA,
            "machine_key": qualification.machine_key(HARDWARE),
            "generated_at": "2026-08-09T00:00:00+00:00",
            "ollama_version": "test",
            "candidates": [
                {
                    "model": "slow:1b", "model_digest": "digest-slow",
                    "status": "qualified", "qualified_roles": ["agent"],
                    "repetitions": 3, "success_rate": 1.0,
                    "median_warm_latency_ms": 900,
                },
                {
                    "model": "fast:1b", "model_digest": "digest-fast",
                    "status": "qualified", "qualified_roles": ["agent"],
                    "repetitions": 3, "success_rate": 1.0,
                    "median_warm_latency_ms": 120,
                },
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        installed = [
            {"name": "slow:1b", "digest": "digest-slow"},
            {"name": "fast:1b", "digest": "digest-fast"},
        ]
        resolved = qualification.resolve(HARDWARE, installed, path=path)
        assert resolved["status"] == "qualified"
        assert resolved["winners"]["agent"]["model"] == "fast:1b"

        recommendation = {"chosen": {"agent": "static:1b"}, "portfolio": {"agent": {}}}
        evidence = qualification.apply_to_recommendation(
            recommendation, HARDWARE, installed, path=path,
        )
        assert evidence["status"] == "qualified"
        assert recommendation["chosen"]["agent"] == "fast:1b"
        assert recommendation["portfolio"]["agent"]["selected_source"] == "runtime_qualification"

        installed[1]["digest"] = "changed"
        fallback = qualification.resolve(HARDWARE, installed, path=path)
        assert fallback["winners"]["agent"]["model"] == "slow:1b"
        drifted = {**HARDWARE, "gpu": "Another GPU"}
        assert qualification.resolve(drifted, installed, path=path)["status"] == "stale_hardware"

    print("Local model qualification OK - machine, digest, repetitions et meilleur candidat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
