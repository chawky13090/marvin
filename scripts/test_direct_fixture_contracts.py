from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"


def load(name: str) -> dict:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def pair(item: dict) -> str:
    return f'{item["tool"]}:{item["action"]}'


def main() -> int:
    classification = load("e7-classification.json")
    strata = load("fixture-strata-policy.json")
    contracts_doc = load("direct-fixture-contracts.json")
    pilot = load("direct-fixture-pilot.json")
    manifest = load("direct-fixture-freeze-manifest.json")

    expected = set(strata["direct_fixture_pairs"])
    contracts = contracts_doc["contracts"]
    assert len(contracts) == 22
    assert {pair(item) for item in contracts} == expected
    assert len({pair(item) for item in contracts}) == len(contracts)
    frozen = {pair(item): item for item in classification["items"] if pair(item) in expected}
    assert len(frozen) == 22

    assert contracts_doc["tool_execution_authorized"] is False
    assert contracts_doc["host_execution_forbidden"] is True
    for item in contracts:
        key = pair(item)
        assert item["class"] == frozen[key]["class"]
        assert item["surface_profile"] == frozen[key]["surface_profile"]
        assert item["execution_authorized"] is False
        assert item["host_execution_forbidden"] is True
        for section in ("setup", "observation", "oracle", "recovery"):
            block = item[section]
            assert block["uses_tool_registry"] is False
            assert block["public_tools_used"] == []
        assert item["setup"]["calls_system_under_test"] is False
        assert item["oracle"]["independent_from_executor"] is True
        assert item["recovery"]["independent_from_executor"] is True
        if item["class"] == "R":
            assert item["recovery"]["expected_fidelity"] == "exact_identity"
            assert item["recovery"]["residual_loss"] == "none"
        elif item["class"] == "C":
            assert item["recovery"]["expected_fidelity"] == "functional_with_declared_residual_loss"
            assert item["recovery"]["residual_loss"] != "none"
        elif item["class"] == "I":
            assert item["recovery"]["expected_fidelity"] == "not_restorable_confinement_required"
            assert item["observation"]["capture_before_and_after"] is True
        elif item["class"] == "N":
            assert item["recovery"]["mechanism"] == "not_applicable"
            assert item["allowed_delta"] == "zero observable mutation"

    by_pair = {pair(item): item for item in contracts}
    assert by_pair["bulk_rename:apply"]["recovery"]["mechanism"] == "filesystem_preimage_restore"
    assert by_pair["bulk_rename:apply"]["recovery"]["component"] != "bulk_rename:rollback"
    rollback_setup = by_pair["bulk_rename:rollback"]["setup"]
    assert rollback_setup["component"] == "prebuilt_bulk_rename_rollback_fixture"
    assert rollback_setup["calls_system_under_test"] is False

    pilot_items = pilot["contracts"]
    assert len(pilot_items) == 6
    assert len({item["surface_profile"] for item in pilot_items}) == 6
    assert {item["class"] for item in pilot_items} == {"N", "R", "C", "I"}
    assert {pair(item) for item in pilot_items} == {
        "bulk_rename:preview", "bulk_rename:apply", "note_delete:__default__",
        "long_task_start:__default__", "winget_uninstall:__default__", "pc_process_kill:__default__",
    }
    assert "code_workspace_control:resume" not in {pair(item) for item in pilot_items}

    assert manifest["fixture_implementation_authorized"] is True
    assert manifest["tool_execution_authorized"] is False
    assert manifest["host_execution_forbidden"] is True
    for name, evidence in manifest["files"].items():
        path = BASE / name
        assert path.exists()
        assert path.stat().st_size == evidence["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]

    print("Direct fixture contracts: 22/22 frozen; pilot 6 surfaces; execution locked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
