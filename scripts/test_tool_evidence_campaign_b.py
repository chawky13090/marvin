"""Contrat de pré-inscription de la campagne B."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"


def main() -> int:
    policy = json.loads((BASE / "campaign-b-policy.json").read_text(encoding="utf-8"))
    candidates = json.loads((BASE / "campaign-b-candidates.json").read_text(encoding="utf-8"))
    assert policy["execution_authorized"] is False
    assert policy["mandatory_fixture_contract"]["host_execution_forbidden"] is True
    assert candidates["summary"]["execution_authorized"] is False
    assert candidates["summary"]["next_wave_never_executed_tools"] == 19
    assert candidates["next_wave_never_executed_tools"] == sorted(
        candidates["next_wave_never_executed_tools"]
    )
    assert "winget_uninstall" in candidates["next_wave_never_executed_tools"]
    assert "pc_process_kill" in candidates["next_wave_never_executed_tools"]
    assert candidates["first_wave"]
    assert candidates["summary"]["first_wave_dangerous_tool_action_pairs"] == 36
    assert all(item["dangerous"] is True for item in candidates["first_wave"])
    assert all("E7" in item["missing_evidence"] for item in candidates["first_wave"])
    assert all(item["execution_authorized"] is False for item in candidates["candidates"])
    assert all(item["required_environment"] != "host" for item in candidates["candidates"])
    print("Tool Evidence Campaign B OK - risques prioritaires, exécution verrouillée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
