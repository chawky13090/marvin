"""Contrôle le SLO roulant de Marvin sans lire ni exporter de contenu utilisateur."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any


DEFAULT_URL = "http://127.0.0.1:8005/api/health"


def evaluate(payload: dict[str, Any]) -> tuple[int, str]:
    slo = payload.get("api", {}).get("slo")
    if not isinstance(slo, dict):
        return 2, "SLO indisponible dans /api/health."
    state = slo.get("state")
    samples = slo.get("samples")
    if state not in {"insufficient", "met", "missed"}:
        return 2, "État SLO invalide."
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 0:
        return 2, "Nombre d'échantillons SLO invalide."
    summary = (
        f"state={state} samples={samples} "
        f"availability={slo.get('availability')} "
        f"latency={slo.get('latency_compliance')} "
        f"burn_rate={slo.get('burn_rate')}"
    )
    return (1 if state == "missed" else 0), summary


def fetch_health(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("payload invalide")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if not args.url.startswith(("http://127.0.0.1:", "http://localhost:")):
        print("ECHEC: le gate SLO n'interroge qu'une instance Marvin locale.")
        return 2
    try:
        payload = fetch_health(args.url, min(max(args.timeout, 1.0), 30.0))
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"ECHEC: santé Marvin inaccessible ({type(exc).__name__}).")
        return 2
    code, message = evaluate(payload)
    print(f"SLO Marvin: {message}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
