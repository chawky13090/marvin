from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.2"
POLICY_PATH = BASE / "e7-apply-replay-policy.json"
AUTHORIZATION_PATH = BASE / "e7-apply-replay-authorization.json"
DEFAULT_OUTPUT = BASE / "e7-apply-replay-result.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from e7_apply_fixture import build_apply_fixture, snapshot_apply_tree  # noqa: E402
from e7_apply_oracle_v12 import restore_and_classify, verify_apply_delta  # noqa: E402


class CampaignRefused(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    ).stdout.strip()


def validate_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))
    if policy.get("schema") != "marvin.e7-apply-replay-policy/1.0":
        raise CampaignRefused("replay_policy_schema_invalid")
    if policy.get("cycles") != 5 or policy.get("authorized_contract") != "bulk_rename:apply":
        raise CampaignRefused("replay_scope_invalid")
    if policy.get("runner_may_reclassify_taxonomy") is not False:
        raise CampaignRefused("runner_authority_invalid")
    if authorization.get("execution_authorized") is not True:
        raise CampaignRefused("execution_not_authorized")
    if authorization.get("authorized_cycles") != 5 or authorization.get("authorized_contracts") != ["bulk_rename:apply"]:
        raise CampaignRefused("authorization_scope_invalid")
    if authorization.get("policy_sha256") != sha256(POLICY_PATH):
        raise CampaignRefused("policy_hash_mismatch")
    for relative, expected in authorization.get("frozen_hashes", {}).items():
        path = ROOT / relative
        if not path.is_file() or sha256(path) != expected:
            raise CampaignRefused(f"frozen_source_changed:{relative}")
    return policy, authorization


def require_clean_commit(authorization: dict[str, Any]) -> str:
    tracked = tuple(authorization["frozen_hashes"]) + (
        str(POLICY_PATH.relative_to(ROOT)), str(AUTHORIZATION_PATH.relative_to(ROOT)),
    )
    for relative in tracked:
        git("ls-files", "--error-unmatch", relative)
    if git("diff", "--name-only", "--", *tracked) or git("diff", "--cached", "--name-only", "--", *tracked):
        raise CampaignRefused("frozen_sources_dirty")
    return git("rev-parse", "HEAD")


def load_product_with_isolated_data(data_dir: Path):
    import config
    config.DATA_DIR = data_dir
    for name in ("bulk_rename_rollback_store", "tool_domains.filesystem"):
        sys.modules.pop(name, None)
    import bulk_rename_rollback_store as store
    from tool_domains import filesystem
    if store.STORE_ROOT.resolve() != (data_dir / "rollback" / "bulk-rename").resolve():
        raise CampaignRefused("rollback_store_not_isolated")
    return filesystem, store


def verify_central_manifest(path: Path, root: Path, store_root: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if store_root.resolve() not in resolved.parents or root.resolve() in resolved.parents:
        raise CampaignRefused("manifest_storage_boundary_invalid")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 2 or payload.get("status") != "applied":
        raise CampaignRefused("manifest_contract_invalid")
    return {"path": resolved, "schema_version": 2, "status": "applied", "revision": payload.get("revision")}


async def run_campaign(output: Path) -> dict[str, Any]:
    policy, authorization = validate_frozen_inputs()
    source_commit = require_clean_commit(authorization)
    if output.exists():
        raise CampaignRefused("result_already_exists")
    cycles: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="marvin-e7-apply-v12-") as temporary:
        workspace = Path(temporary).resolve()
        data_dir = workspace / "marvin-data"
        data_dir.mkdir()
        filesystem, store = load_product_with_isolated_data(data_dir)
        for cycle_index in range(1, 6):
            fixture = build_apply_fixture(workspace, cycle_index)
            root, plan, preimage = fixture["root"], fixture["plan"], fixture["preimage"]

            def resolve_fixture_path(raw: str) -> str:
                resolved = Path(raw).resolve()
                if resolved != root:
                    raise CampaignRefused("path_outside_cycle_root")
                return str(resolved)

            filesystem.configure(resolve_path=resolve_fixture_path)
            result = await filesystem.bulk_rename({
                "folder": str(root), "pattern": r"^old-(.*)\.txt$", "replace": r"new-\1.txt",
                "glob": "*.txt", "action": "apply", "confirmed": True,
            })
            success = isinstance(result, dict) and result.get("success") is True
            post_apply = snapshot_apply_tree(root)
            delta = verify_apply_delta(preimage, post_apply, plan)
            manifest = verify_central_manifest(Path(str(result.get("rollback_manifest"))), root, store.STORE_ROOT) if success else None
            verdict, recovery = restore_and_classify(
                root, plan, preimage, tool_success=bool(success and delta["valid"]),
                allowed_residual_fields=frozenset(policy["c_candidate_predicate"]["allowed_residual_fields"]),
            )
            if manifest:
                manifest["path"].unlink()
            cycle = {
                "cycle": cycle_index, "verdict": verdict, "business_tool_invocations": 1,
                "tool_success": success, "declared_delta_valid": delta["valid"],
                "relative_observed_delta": delta["delta"], "identity_preserved_during_apply": delta["identity_preserved"],
                "central_manifest_verified": manifest is not None,
                "exact_identity_restored": recovery["exact_identity_restored"],
                "acl_added_rights": recovery["acl_added_rights"],
                "residual_fields": recovery["residual_fields"],
                "independent_recovery_error": recovery["independent_recovery_error"],
                "preimage_sha256": canonical_hash(preimage),
                "post_apply_sha256": canonical_hash(post_apply),
                "restored_sha256": canonical_hash(recovery["restored"]),
            }
            cycles.append(cycle)
            shutil.rmtree(root.parent)
    normalized = [{key: item[key] for key in (
        "verdict", "business_tool_invocations", "tool_success", "declared_delta_valid",
        "relative_observed_delta", "identity_preserved_during_apply", "central_manifest_verified",
        "exact_identity_restored", "acl_added_rights", "independent_recovery_error",
        "residual_fields",
    )} for item in cycles]
    identical = len(normalized) == 5 and all(item == normalized[0] for item in normalized[1:])
    verdicts = {item["verdict"] for item in cycles}
    final = next(iter(verdicts)) if identical and len(cycles) == 5 and len(verdicts) == 1 else "FAILED_LOCKED"
    evidence = {
        "schema": "marvin.e7-apply-replay-result/1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract": "bulk_rename:apply", "source_commit": source_commit,
        "policy_sha256": sha256(POLICY_PATH), "authorization_sha256": sha256(AUTHORIZATION_PATH),
        "final_verdict": final, "runner_reclassified_taxonomy": False,
        "cycles_required": 5, "cycles_completed": len(cycles), "normalized_cycles_identical": identical,
        "business_tools_invoked": [{"tool": "bulk_rename", "action": "apply", "count": len(cycles)}],
        "fixture_contains_user_data": False, "real_marvin_data_dir_used": False,
        "persistent_host_paths_used": False, "cycles": cycles,
        "next_action": policy["verdict_actions"][final],
        "rollback": "delete_this_result_artifact; all isolated fixtures and manifests were independently removed",
    }
    evidence["content_sha256"] = canonical_hash(evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(".json.tmp")
    temporary_output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_output, output)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result = asyncio.run(run_campaign(parser.parse_args().output.resolve()))
    print(json.dumps({"final_verdict": result["final_verdict"], "cycles": result["cycles_completed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
