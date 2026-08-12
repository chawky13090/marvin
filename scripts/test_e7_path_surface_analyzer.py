from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from e7_path_surface_analyzer import PathAnalyzer  # noqa: E402
from e7_surface_analyzer import ProjectIndex  # noqa: E402

FIXTURES = ROOT / "scripts" / "fixtures"
V13_RULES = json.loads((ROOT / "benchmarks/tool-evidence/v1.3/surface-analysis-rules.json").read_text(encoding="utf-8"))
V14_RULES = json.loads((ROOT / "benchmarks/tool-evidence/v1.4/path-analysis-rules.json").read_text(encoding="utf-8"))


def run(index: ProjectIndex, name: str, env: dict[str, object]):
    analyzer = PathAnalyzer(index, V13_RULES, V14_RULES)
    analyzer.walk(name, env)
    return analyzer.result


def mutations(result) -> set[tuple[str, str]]:
    return {
        (str(item["effect"]), str(item["operation"]))
        for item in result.compatible
        if item["operation"] not in {"READ", "OBSERVE"}
    }


def main() -> int:
    paths = [
        FIXTURES / "e7_path_analysis_prospective_canaries.py",
        FIXTURES / "e7_path_analysis_process_canary.py",
    ]
    index = ProjectIndex(paths, source_root=FIXTURES)
    prefix = "e7_path_analysis_prospective_canaries"
    false_result = run(index, f"{prefix}.early_return", {"args": {"confirmed": False}, "root": "@type:pathlib.Path"})
    true_result = run(index, f"{prefix}.early_return", {"args": {"confirmed": True}, "root": "@type:pathlib.Path"})
    status_result = run(index, f"{prefix}.nested_action", {"args": {"action": "status"}, "root": "@type:pathlib.Path"})
    apply_result = run(index, f"{prefix}.nested_action", {"args": {"action": "apply"}, "root": "@type:pathlib.Path"})
    dynamic_result = run(index, f"{prefix}.dynamic_guard", {"args": {}, "root": "@type:pathlib.Path"})
    process_prefix = "e7_path_analysis_process_canary"
    observed = run(index, f"{process_prefix}.observe_process", {"pid": 123})
    mutated = run(index, f"{process_prefix}.mutate_process", {"pid": 123})

    assert not mutations(false_result)
    assert ("filesystem", "UPDATE") in mutations(true_result)
    assert not mutations(status_result)
    assert ("filesystem", "CREATE") in mutations(apply_result)
    assert dynamic_result.unresolved
    assert any(item["effect"] == "process" and item["operation"] == "OBSERVE" for item in observed.compatible)
    assert not mutations(observed)
    assert ("process", "EXECUTE") in mutations(mutated)
    print("E7 Path Surface Analyzer OK - 7 prospective canaries in both directions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
