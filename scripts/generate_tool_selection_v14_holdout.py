"""Génère le holdout v1.4 avec les rôles Cloud indépendants déjà audités."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_tool_selection_v13_holdout as generator  # noqa: E402


BASE = ROOT / "benchmarks/tool-selection/v1.4"
POLICY = BASE / "holdout-generation-freeze.json"
CORPUS = BASE / "holdout-corpus.json"
ORACLE = BASE / "holdout-oracle.json"
REPORT = BASE / "holdout-generation-report.json"


def _references() -> list[str]:
    paths = (
        ROOT / "benchmarks/tool-selection/v1.2/holdout-corpus.json",
        ROOT / "benchmarks/tool-selection/v1.3/holdout-corpus.json",
        ROOT / "benchmarks/windows-operator/v1.1/intent-corpus.json",
        ROOT / "benchmarks/tool-recovery/v1.2/development-corpus.json",
    )
    values: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("items") or []:
            value = str(row.get("prompt") or row.get("unknown_name") or "")
            value = value.replace("_", " ").strip()
            if value:
                values.append(value)
    return values


def _rename_id(value: str) -> str:
    return value.replace("v13-", "v14-", 1)


def _artifact_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def _normalize_public_artifacts() -> dict[str, Any]:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    oracle = json.loads(ORACLE.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    corpus["schema"] = "marvin.tool-selection-v14-holdout/1.0"
    oracle["schema"] = "marvin.tool-selection-v14-oracle/1.0"
    report["schema"] = "marvin.tool-selection-v14-generation-report/1.0"
    for row in corpus["items"]:
        row["id"] = _rename_id(str(row["id"]))
    for row in oracle["items"]:
        row["id"] = _rename_id(str(row["id"]))
    selected_ids = sorted(str(row["id"]) for row in corpus["items"])
    report["generator_base_sha256"] = generator._sha256(Path(generator.__file__))
    report["generator_wrapper_sha256"] = generator._sha256(Path(__file__))
    report["corpus_sha256"] = hashlib.sha256(_artifact_bytes(corpus)).hexdigest()
    report["oracle_sha256"] = hashlib.sha256(_artifact_bytes(oracle)).hexdigest()
    report["selected_ids_sha256"] = hashlib.sha256(
        generator._canonical(selected_ids)
    ).hexdigest()
    generator._atomic(CORPUS, corpus)
    generator._atomic(ORACLE, oracle)
    generator._atomic(REPORT, report)
    return report


async def run() -> dict[str, Any]:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if generator._sha256(Path(__file__)) != policy["generator_wrapper_sha256"]:
        raise RuntimeError("Wrapper v1.4 modifié après gel.")
    generator.BASE = BASE
    generator.POLICY = POLICY
    generator.CORPUS = CORPUS
    generator.ORACLE = ORACLE
    generator.REPORT = REPORT
    generator._reference_prompts = _references
    await generator.run()
    return _normalize_public_artifacts()


def main() -> int:
    report = asyncio.run(run())
    print(json.dumps(report["counts"], ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
