"""Validate the frozen independent terminal oracle and its import boundary."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import software_terminal_oracle_v1 as oracle


POLICY = ROOT / "benchmarks/tool-selection/v1.8/software-terminal-oracle-preregistration.json"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module.split(".", 1)[0])
    return result


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_oracle_implementation"
    contracts = value["intent_contracts"]
    assert len(contracts) == 7
    assert set(contracts) == {
        "software.search", "software.install", "software.inventory",
        "software.updates_check", "software.upgrade", "software.uninstall",
        "software.manual_panel",
    }
    mutations = {"winget_install", "winget_upgrade", "winget_uninstall"}
    for intent, contract in contracts.items():
        tools = {call["tool"] for call in contract["accepted_terminal_calls"]}
        if contract["mutation_allowed"]:
            assert tools <= mutations and tools
        else:
            assert not (tools & mutations), intent

    for intent, contract in contracts.items():
        expected = [
            {"tool": call["tool"], "action": call["action"], "constraints": []}
            for call in contract["accepted_terminal_calls"]
        ]
        item = {"id": "generic", "intent": intent, "prompt": "not inspected by oracle"}
        assert oracle.accepted_calls_for_reviewed_item(
            item, contracts, reviewer_a_valid=True, reviewer_b_valid=True
        ) == expected
        assert oracle.accepted_calls_for_reviewed_item(
            item, contracts, reviewer_a_valid=False, reviewer_b_valid=True
        ) == []
        assert oracle.accepted_calls_for_reviewed_item(
            item, contracts, reviewer_a_valid=True, reviewer_b_valid=False
        ) == []
    assert oracle.accepted_calls_for_reviewed_item(
        {"intent": "software.unknown"}, contracts,
        reviewer_a_valid=True, reviewer_b_valid=True,
    ) == []

    imports = _imports(SCRIPTS / "software_terminal_oracle_v1.py")
    assert imports <= {"__future__", "typing"}
    assert not {
        "tools", "agent_tool_selection", "tool_router", "capability_discovery",
        "tool_capability_ranking", "generate_tool_selection_v15_holdout_r3",
    } & imports
    independence = value["independence"]
    assert independence["oracle_imports_product_code"] is False
    assert independence["oracle_reads_product_registry"] is False
    assert independence["shared_source_file_or_generated_taxonomy"] is False
    assert value["future_r5"]["cloud_generation_authorized_by_this_artifact"] is False
    print("Tool Selection v1.8 Terminal Oracle OK - calculable, dual-review gated, product-independent")


if __name__ == "__main__":
    main()
