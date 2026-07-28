"""Live smoke test for the configured Debian Hyper-V Test Forge runner."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import linux_test_runner  # noqa: E402


FILES = {
    "main.sh": """#!/usr/bin/env bash
set -Eeuo pipefail
double() {
  printf '%s\n' "$(( $1 * 2 ))"
}
""",
    "integration.sh": """#!/usr/bin/env bash
set -Eeuo pipefail
source ./main.sh
test "$(double 21)" = "42"
""",
    "test_main.bats": """#!/usr/bin/env bats
@test "double calcule 42" {
  source ./main.sh
  [ "$(double 21)" = "42" ]
}
""",
}


def main() -> int:
    status = linux_test_runner.status()
    if not status.get("ready"):
        raise SystemExit(
            "Runner Debian indisponible: " + str(status.get("error"))
        )
    result = linux_test_runner.execute(
        FILES,
        timeout_seconds=900,
        capture_result=True,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    try:
        if not result.get("production_ready"):
            raise SystemExit(
                "Le smoke test Debian natif n'est pas production_ready."
            )
        isolation = result.get("isolation") or {}
        if isolation.get("host_network_modified") is not False:
            raise SystemExit("Le runner a modifié le réseau hôte.")
        if not (
            isolation.get("checkpoint_restored_before")
            and isolation.get("checkpoint_restored_after")
        ):
            raise SystemExit("La restauration du checkpoint n'est pas prouvée.")
        return 0
    finally:
        session = linux_test_runner.status().get("result_session")
        if session:
            restored = linux_test_runner.restore_clean(confirmed=True)
            print(json.dumps(
                {"cleanup": restored},
                ensure_ascii=False,
                indent=2,
            ))


if __name__ == "__main__":
    raise SystemExit(main())
