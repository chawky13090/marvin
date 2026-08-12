from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    oracle_path = ROOT / "scripts" / "e7_apply_oracle_v12.py"
    tree = ast.parse(oracle_path.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])
    }
    assert not imports & {"backend", "tools", "tool_domains", "bulk_rename_rollback_store"}

    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from e7_apply_fixture import build_apply_fixture, snapshot_apply_tree
    from e7_apply_oracle_v12 import restore_and_classify, verify_apply_delta

    with tempfile.TemporaryDirectory(prefix="e7-oracle-v12-") as temporary:
        workspace = Path(temporary).resolve()
        fixture = build_apply_fixture(workspace, 1)
        root, plan, preimage = fixture["root"], fixture["plan"], fixture["preimage"]
        for source, target in plan.items():
            os.rename(root / source, root / target)
        delta = verify_apply_delta(preimage, snapshot_apply_tree(root), plan)
        assert delta["valid"] is True
        verdict, details = restore_and_classify(root, plan, preimage, tool_success=True)
        assert verdict == "R_CONFIRMED" and details["exact_identity_restored"] is True

    policy = json.loads((BASE / "e7-apply-replay-policy.json").read_text(encoding="utf-8"))
    authorization = json.loads((BASE / "e7-apply-replay-authorization.json").read_text(encoding="utf-8"))
    assert policy["cycles"] == 5 and policy["runner_may_reclassify_taxonomy"] is False
    assert authorization["execution_authorized"] is True
    assert authorization["authorized_contracts"] == ["bulk_rename:apply"]
    assert authorization["policy_sha256"] == sha256(BASE / "e7-apply-replay-policy.json")
    for relative, expected in authorization["frozen_hashes"].items():
        assert sha256(ROOT / relative) == expected, relative
    assert not (BASE / "e7-apply-replay-result.json").exists(), "result must not exist before frozen execution"
    print("E7 Apply Replay v1.2 OK - independent oracle, frozen runner, five cycles authorized but not executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
