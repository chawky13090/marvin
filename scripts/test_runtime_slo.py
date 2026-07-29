"""Contrats déterministes du gate SLO local."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_runtime_slo import evaluate


def payload(state: str, samples: int = 100) -> dict:
    return {
        "api": {
            "slo": {
                "state": state,
                "samples": samples,
                "availability": 0.99,
                "latency_compliance": 0.98,
                "burn_rate": 1.0,
            }
        }
    }


def main() -> int:
    assert evaluate(payload("met"))[0] == 0
    assert evaluate(payload("insufficient", 2))[0] == 0
    assert evaluate(payload("missed"))[0] == 1
    assert evaluate({})[0] == 2
    assert evaluate(payload("unknown"))[0] == 2
    assert evaluate(payload("met", -1))[0] == 2
    assert evaluate(payload("met", True))[0] == 2
    print("Runtime SLO OK - succès, budget épuisé, données insuffisantes et schéma invalide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
