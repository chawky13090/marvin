"""Contrat de pré-inscription de la campagne B."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1"


def main() -> int:
    policy = json.loads((BASE / "campaign-b-policy.json").read_text(encoding="utf-8"))
    candidates = json.loads((BASE / "campaign-b-candidates.json").read_text(encoding="utf-8"))
    assert policy["execution_authorized"] is False
    assert policy["mandatory_fixture_contract"]["host_execution_forbidden"] is True
    assert candidates["summary"]["execution_authorized"] is False
    assert candidates["summary"]["first_wave_never_executed_tools"] == 19
    assert candidates["first_wave_tools"] == sorted(candidates["first_wave_tools"])
    assert "winget_uninstall" in candidates["first_wave_tools"]
    assert "pc_process_kill" in candidates["first_wave_tools"]
    assert all(item["execution_authorized"] is False for item in candidates["candidates"])
    assert all(item["required_environment"] != "host" for item in candidates["candidates"])
    print("Tool Evidence Campaign B OK - 19 outils initiaux, exécution verrouillée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
