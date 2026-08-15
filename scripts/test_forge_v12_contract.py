"""Verifie le pre-enregistrement et l'independance de Forge v1.2."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
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


def _local_import_closure(entry: Path, root: Path) -> set[str]:
    pending = [entry]
    visited: set[Path] = set()
    modules: set[str] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        for module in _imports(path):
            candidate = root / f"{module}.py"
            if candidate.is_file():
                modules.add(module)
                pending.append(candidate)
    return modules


def main() -> int:
    policy = json.loads((CONTRACT / "acceptance-policy.json").read_text(encoding="utf-8"))
    erratum = json.loads((CONTRACT / "acceptance-policy-erratum-v1.1.json").read_text(encoding="utf-8"))
    corpus = json.loads((CONTRACT / "development-corpus.json").read_text(encoding="utf-8"))
    shared_ranking = json.loads((CONTRACT / "shared-ranking-non-regression.json").read_text(encoding="utf-8"))
    assert policy["status"] == "pre_registered_before_product_implementation"
    assert policy["execution_contract"]["implicit_substitution_execution_forbidden"] is True
    assert policy["decision"]["generalize"]["false_replacement_count"] == 0
    assert policy["campaign"]["current_release_scope_until_holdout_exists"] == "development_only"
    assert hashlib.sha256((CONTRACT / "acceptance-policy.json").read_bytes()).hexdigest() == erratum["original_policy_sha256"]
    for relative_path, expected_hash in erratum["shared_production_source_hashes"].items():
        frozen = subprocess.check_output(
            [
                "git",
                "show",
                f"{erratum['shared_production_ranking_baseline_commit']}:{relative_path}",
            ],
            cwd=ROOT,
        )
        assert hashlib.sha256(frozen).hexdigest() == expected_hash
    assert erratum["constraints"]["any_shared_ranking_change_requires_new_baseline_and_new_holdout"] is True
    assert erratum["constraints"]["no_ranking_lexicon_or_constant_change_after_corpus_freeze_without_regel"] is True
    assert erratum["constraints"]["minimum_names_per_evaluated_family"] == 5
    assert erratum["constraints"]["full_21_family_holdout_minimum_names"] == 105
    assert shared_ranking["intentions"] == 120
    assert shared_ranking["changed_rankings"] == 0
    assert shared_ranking["identical"] is True
    assert shared_ranking["baseline_source_sha256"] == shared_ranking["current_source_sha256"]
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

    product_closure = _local_import_closure(
        ROOT / "backend/unknown_tool_resolver.py",
        ROOT / "backend",
    )
    assert not {"forge_v12_oracle", "test_forge_v12_contract"} & product_closure
    oracle_closure = _local_import_closure(oracle, ROOT / "scripts")
    assert not {
        "unknown_tool_resolver", "agent_execution", "capability_catalog",
        "capability_discovery", "tool_capability_ranking",
    } & oracle_closure

    print("Forge v1.2 contract OK - 24 noms inedits, seuils geles et oracle independant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
