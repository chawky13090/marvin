"""Contrôle post-publication de l'appareil E7 v1.2 sans réécrire le test gelé."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.2"
POLICY = BASE / "e7-apply-replay-policy.json"
AUTHORIZATION = BASE / "e7-apply-replay-authorization.json"
RESULT = BASE / "e7-apply-replay-result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blob_sha256(commit: str, relative: str) -> str:
    return hashlib.sha256(subprocess.run(
        ["git", "show", f"{commit}:{relative}"], cwd=ROOT,
        check=True, capture_output=True,
    ).stdout).hexdigest()


def main() -> int:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    result = json.loads(RESULT.read_text(encoding="utf-8"))

    assert policy["runner_may_reclassify_taxonomy"] is False
    assert policy["isolation"]["real_marvin_data_dir_forbidden"] is True
    assert policy["isolation"]["bulk_rename_rollback_tool_forbidden"] is True
    assert authorization["execution_authorized"] is True
    assert authorization["authorized_contracts"] == ["bulk_rename:apply"]
    assert authorization["authorized_cycles"] == 5
    assert authorization["policy_sha256"] == sha256(POLICY)
    assert result["policy_sha256"] == sha256(POLICY)
    assert result["authorization_sha256"] == sha256(AUTHORIZATION)

    source_commit = str(result["source_commit"])
    for relative, expected in authorization["frozen_hashes"].items():
        assert blob_sha256(source_commit, relative) == expected, relative

    oracle_path = ROOT / "scripts" / "e7_apply_oracle_v12.py"
    tree = ast.parse(oracle_path.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (
            node.names if isinstance(node, ast.Import)
            else [ast.alias(node.module or "")]
        )
    }
    assert not imports & {"backend", "tools", "tool_domains", "bulk_rename_rollback_store"}

    assert result["source_commit"] == "1d317a148b3c594d2129ffd06f084c6bec36c713"
    assert authorization["authorization_expires_when"] == (
        "result_artifact_exists_or_any_frozen_hash_changes"
    )
    print("E7 Apply Replay Freeze post-result OK - runner, oracle, policy and authorization remain frozen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
