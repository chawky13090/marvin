"""Exécute des scénarios Marvin Forge contre le backend déjà démarré."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx


BACKEND = os.getenv("MARVIN_BACKEND_URL", "http://127.0.0.1:8005").rstrip("/")


def read_scenarios(client: httpx.Client) -> list[dict]:
    response = client.get(f"{BACKEND}/api/forge/scenarios")
    response.raise_for_status()
    return response.json().get("scenarios", [])


def execute(client: httpx.Client, scenario: dict) -> dict:
    payload = {
        "messages": [{"role": "user", "content": scenario["prompt"]}],
        "model": scenario.get("model"),
        "cortex": scenario.get("cortex") or {},
    }
    events: list[dict] = []
    started = time.perf_counter()
    with client.stream("POST", f"{BACKEND}/api/chat", json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                events.append({"type": "error", "message": "Événement SSE JSON invalide"})
    duration_ms = int((time.perf_counter() - started) * 1000)
    grade_response = client.post(
        f"{BACKEND}/api/forge/grade",
        json={
            "scenario_id": scenario["id"],
            "events": events,
            "duration_ms": duration_ms,
            "persist": True,
        },
    )
    grade_response.raise_for_status()
    return grade_response.json()["run"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Runner Marvin Forge")
    parser.add_argument("--scenario", action="append", default=[], help="identifiant à exécuter")
    parser.add_argument("--all-enabled", action="store_true", help="exécute tous les scénarios actifs")
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 11))
    parser.add_argument("--list", action="store_true", help="liste le corpus sans exécuter")
    args = parser.parse_args()

    timeout = httpx.Timeout(connect=10, read=660, write=30, pool=10)
    with httpx.Client(timeout=timeout) as client:
        scenarios = read_scenarios(client)
        if args.list:
            for item in scenarios:
                print(f"{item['id']}: {'actif' if item['enabled'] else 'inactif'} - {item['name']}")
            return 0

        requested = set(args.scenario)
        selected = [
            item for item in scenarios
            if item["id"] in requested or (args.all_enabled and item["enabled"])
        ]
        if not selected:
            print("Aucun scénario sélectionné. Utilisez --list, --scenario ID ou --all-enabled.", file=sys.stderr)
            return 2

        failed = 0
        for item in selected:
            for attempt in range(1, args.repeat + 1):
                run = execute(client, item)
                status = "OK" if run["success"] else "ECHEC"
                print(
                    f"[{status}] {item['id']} essai {attempt}/{args.repeat} "
                    f"score={run['score']:.2%} durée={run.get('duration_ms')}ms "
                    f"outils={run.get('tool_names') or []}"
                )
                failed += 0 if run["success"] else 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
