"""Verifie le pre-enregistrement et l'independance de Forge v1.2."""

from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "benchmarks" / "tool-recovery" / "v1.2"
OBSERVED_V1_NAMES = {
    "pc_file_search", "pc_find_files", "pc_search_files", "find_files", "pc_open_app"
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def main() -> int:
    policy = json.loads((CONTRACT / "acceptance-policy.json").read_text(encoding="utf-8"))
    corpus = json.loads((CONTRACT / "development-corpus.json").read_text(encoding="utf-8"))
    assert policy["status"] == "pre_registered_before_product_implementation"
    assert policy["execution_contract"]["implicit_substitution_execution_forbidden"] is True
    assert policy["decision"]["generalize"]["false_replacement_count"] == 0
    assert policy["campaign"]["current_release_scope_until_holdout_exists"] == "development_only"
    items = corpus["items"]
    assert len(items) == 24
    assert len({item["id"] for item in items}) == 24
    assert not (OBSERVED_V1_NAMES & {item["unknown_name"] for item in items})
    assert any(not item["acceptable_tools"] for item in items)
    assert all(item["forbidden_tools"] for item in items)

    oracle = ROOT / "scripts" / "forge_v12_oracle.py"
    imports = _imports(oracle)
    assert imports <= {"__future__", "typing"}
    assert not {
        "tools", "capability_catalog", "capability_discovery", "tool_router",
        "unknown_tool_resolver", "agent_execution"
    } & imports

    print("Forge v1.2 contract OK - 24 noms inedits, seuils geles et oracle independant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
