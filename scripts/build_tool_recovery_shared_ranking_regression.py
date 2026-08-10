"""Compare le classement lexical vif au classement gele avant Forge v1.2."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tool_capability_ranking as current_ranking
from capability_discovery import parameter_text, profile_for
from tools import TOOLS_SPEC


BASELINE_COMMIT = "3ebef3f"


def _git_blob(path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{BASELINE_COMMIT}:{path}"], cwd=ROOT)


def _baseline_module() -> types.ModuleType:
    name = "_marvin_frozen_tool_capability_ranking"
    module = types.ModuleType(name)
    module.__file__ = f"git:{BASELINE_COMMIT}:backend/tool_capability_ranking.py"
    sys.modules[name] = module
    exec(compile(_git_blob("backend/tool_capability_ranking.py"), module.__file__, "exec"), module.__dict__)
    return module


def _documents() -> tuple[dict[str, str], dict[str, str]]:
    discovery: dict[str, str] = {}
    exclusions: dict[str, str] = {}
    for specification in TOOLS_SPEC:
        function = specification.get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        profile = profile_for(name)
        discovery[name] = profile.search_document(
            name,
            str(function.get("description") or ""),
            parameter_text(function),
        )
        exclusions[name] = " ".join(profile.do_not_use_when)
    return discovery, exclusions


def main() -> int:
    corpus_path = ROOT / "benchmarks/windows-operator/v1.1/intent-corpus.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    frozen = _baseline_module()
    discovery, exclusions = _documents()
    frozen_catalog = frozen.build_catalog(TOOLS_SPEC, discovery, exclusions)
    current_catalog = current_ranking.build_catalog(TOOLS_SPEC, discovery, exclusions)
    rows: list[dict[str, Any]] = []
    changed = 0
    for item in corpus["items"]:
        before = [name for name, _score in frozen.rank_capabilities(
            item["prompt"], frozen_catalog, limit=20, min_score=1.5
        )]
        after = [name for name, _score in current_ranking.rank_capabilities(
            item["prompt"], current_catalog, limit=20, min_score=1.5
        )]
        is_changed = before != after
        changed += int(is_changed)
        rows.append({"id": item["id"], "changed": is_changed, "before": before, "after": after})
    report = {
        "schema": "marvin.shared-ranking-regression/1.0",
        "scope": "shared_lexical_ranking_stage_only",
        "baseline_commit": BASELINE_COMMIT,
        "corpus": "benchmarks/windows-operator/v1.1/intent-corpus.json",
        "intentions": len(rows),
        "changed_rankings": changed,
        "identical": changed == 0,
        "baseline_source_sha256": hashlib.sha256(_git_blob("backend/tool_capability_ranking.py")).hexdigest(),
        "current_source_sha256": hashlib.sha256((BACKEND / "tool_capability_ranking.py").read_bytes()).hexdigest(),
        "limitation": "Cette preuve couvre l'etage lexical partage affecte par les alias, pas les sorties stochastiques du LLM.",
        "items": rows,
    }
    output = ROOT / "benchmarks/tool-recovery/v1.2/shared-ranking-non-regression.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"intentions": len(rows), "changed_rankings": changed, "identical": changed == 0}))
    return 0 if changed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
