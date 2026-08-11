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
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
POLICY_PATH = BASE / "e7-apply-execution-policy.json"
AUTHORIZATION_PATH = BASE / "e7-apply-execution-authorization.json"
DEFAULT_OUTPUT = BASE / "e7-apply-execution-result.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from e7_apply_fixture import (  # noqa: E402
    ApplyFixtureError,
    assert_declared_rename_delta,
    build_apply_fixture,
    restore_by_inverse_rename,
    snapshot_apply_tree,
)
from tool_domains import filesystem as filesystem_domain  # noqa: E402


class CampaignRefused(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    return completed.stdout.strip()


def _validate_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any], tuple[str, ...]]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    authorization = json.loads(AUTHORIZATION_PATH.read_text(encoding="utf-8"))
    if policy.get("schema") != "marvin.e7-apply-execution-policy/1.0":
        raise CampaignRefused("e7_apply_policy_schema_invalid")
    if policy.get("authorized_contract") != "bulk_rename:apply":
        raise CampaignRefused("e7_apply_scope_invalid")
    if policy.get("cycles") != 5 or policy.get("maximum_total_business_tool_invocations") != 5:
        raise CampaignRefused("e7_apply_budget_invalid")
    if policy.get("runner_may_reclassify_taxonomy") is not False:
        raise CampaignRefused("e7_apply_runner_authority_invalid")
    if authorization.get("schema") != "marvin.e7-apply-execution-authorization/1.0":
        raise CampaignRefused("e7_apply_authorization_schema_invalid")
    if authorization.get("execution_authorized") is not True:
        raise CampaignRefused("e7_apply_execution_not_authorized")
    if authorization.get("authorized_contracts") != ["bulk_rename:apply"]:
        raise CampaignRefused("e7_apply_authorization_scope_invalid")
    if authorization.get("authorized_cycles") != 5:
        raise CampaignRefused("e7_apply_authorization_cycles_invalid")
    if authorization.get("host_persistent_paths_forbidden") is not True:
        raise CampaignRefused("e7_apply_persistent_host_path_not_forbidden")
    if authorization.get("policy_sha256") != _sha256(POLICY_PATH):
        raise CampaignRefused("e7_apply_policy_hash_mismatch")
    governed = tuple(policy.get("governed_source_hashes") or {})
    if not governed:
        raise CampaignRefused("e7_apply_governed_sources_missing")
    for relative, expected in policy["governed_source_hashes"].items():
        path = ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            raise CampaignRefused(f"e7_apply_source_changed:{relative}")
    for relative, expected in authorization.get("frozen_hashes", {}).items():
        path = ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            raise CampaignRefused(f"e7_apply_authorized_source_changed:{relative}")
    return policy, authorization, governed


def _require_committed_clean_sources(governed: tuple[str, ...]) -> str:
    tracked = (*governed, str(POLICY_PATH.relative_to(ROOT)), str(AUTHORIZATION_PATH.relative_to(ROOT)))
    for relative in tracked:
        _git("ls-files", "--error-unmatch", relative)
    if _git("diff", "--name-only", "--", *tracked):
        raise CampaignRefused("e7_apply_governed_sources_dirty")
    if _git("diff", "--cached", "--name-only", "--", *tracked):
        raise CampaignRefused("e7_apply_governed_sources_staged")
    return _git("rev-parse", "HEAD")


def _relative_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[str]]:
    before_keys = set(before)
    after_keys = set(after)
    changed = sorted(key for key in before_keys & after_keys if before[key] != after[key])
    return {
        "removed": sorted(before_keys - after_keys),
        "added": sorted(after_keys - before_keys),
        "changed": changed,
    }


def _acl_added_rights(before_sddl: str, after_sddl: str) -> list[str]:
    # La classe C est volontairement plus stricte que le simple delta effectif :
    # toute ACE nouvelle est refusée. Une égalité SDDL reste exigée pour R.
    def aces(value: str) -> set[str]:
        dacl = value.split("D:", 1)[1] if "D:" in value else ""
        return {f"({item}" for item in dacl.split("(")[1:]}
    return sorted(aces(after_sddl) - aces(before_sddl))


def _classify_cycle(
    policy: Mapping[str, Any], preimage: Mapping[str, Any], post_apply: Mapping[str, Any],
    restored: Mapping[str, Any], plan: Mapping[str, str], tool_success: bool,
) -> tuple[str, dict[str, Any]]:
    delta = _relative_delta(preimage, post_apply)
    declared = set(plan) | set(plan.values())
    observed = set(delta["removed"]) | set(delta["added"]) | set(delta["changed"])
    collateral = sorted(observed - declared)
    exact = restored == preimage
    acl_additions: dict[str, list[str]] = {}
    for relative in sorted(set(preimage) & set(restored)):
        added = _acl_added_rights(preimage[relative]["acl_sddl"], restored[relative]["acl_sddl"])
        if added:
            acl_additions[relative] = added
    strict_r = tool_success and not collateral and exact and not acl_additions
    if strict_r:
        return "R_CONFIRMED", {"collateral": [], "acl_added_rights": {}, "residual_fields": []}

    allowed = set(policy["c_candidate_predicate"]["allowed_residual_fields"])
    residual_fields: set[str] = set()
    forbidden_difference = False
    if set(preimage) != set(restored):
        forbidden_difference = True
    else:
        for relative in preimage:
            before_item = preimage[relative]
            after_item = restored[relative]
            for field in set(before_item) | set(after_item):
                if before_item.get(field) != after_item.get(field):
                    residual_fields.add(field)
                    if field not in allowed:
                        forbidden_difference = True
    c_candidate = (
        tool_success
        and not collateral
        and not acl_additions
        and bool(residual_fields)
        and not forbidden_difference
    )
    verdict = "R_INVALID_C_CANDIDATE" if c_candidate else "FAILED_LOCKED"
    return verdict, {
        "collateral": collateral,
        "acl_added_rights": acl_additions,
        "residual_fields": sorted(residual_fields),
    }


def _remove_tool_metadata_for_independent_recovery(root: Path, result: Mapping[str, Any]) -> list[str]:
    removed: list[str] = []
    raw = result.get("rollback_manifest")
    if not raw:
        return removed
    manifest = Path(str(raw)).resolve(strict=False)
    root_resolved = root.resolve(strict=True)
    if root_resolved not in manifest.parents:
        raise CampaignRefused("e7_apply_manifest_outside_fixture")
    rollback_dir = manifest.parent
    if manifest.is_file():
        manifest.unlink()
        removed.append(manifest.relative_to(root_resolved).as_posix())
    if rollback_dir.is_dir() and not any(rollback_dir.iterdir()):
        rollback_dir.rmdir()
    return removed


async def run_campaign(output: Path) -> dict[str, Any]:
    policy, authorization, governed = _validate_frozen_inputs()
    source_commit = _require_committed_clean_sources(governed)
    if output.exists():
        raise CampaignRefused("e7_apply_result_already_exists")

    cycles: list[dict[str, Any]] = []
    stop_after_cycle = False
    with tempfile.TemporaryDirectory(prefix="marvin-e7-apply-") as temporary:
        workspace = Path(temporary).resolve()
        for cycle_index in range(1, 6):
            if stop_after_cycle:
                break
            fixture = build_apply_fixture(workspace, cycle_index)
            root = fixture["root"]
            plan = fixture["plan"]
            preimage = fixture["preimage"]

            def resolve_fixture_path(raw: str) -> str:
                resolved = Path(raw).resolve()
                if resolved != root:
                    raise CampaignRefused("e7_apply_path_outside_cycle_root")
                return str(resolved)

            filesystem_domain.configure(resolve_path=resolve_fixture_path)
            tool_result = await filesystem_domain.bulk_rename({
                "folder": str(root),
                "pattern": r"^old-(.*)\.txt$",
                "replace": r"new-\1.txt",
                "glob": "*.txt",
                "action": "apply",
                "confirmed": True,
            })
            tool_success = bool(isinstance(tool_result, dict) and tool_result.get("success") is True)
            post_apply = snapshot_apply_tree(root)
            declared_delta_valid = True
            declared_delta_error = None
            try:
                assert_declared_rename_delta(preimage, post_apply, plan)
            except ApplyFixtureError as exc:
                declared_delta_valid = False
                declared_delta_error = str(exc)

            metadata_removed = _remove_tool_metadata_for_independent_recovery(root, tool_result)
            recovery_error = None
            try:
                restore_by_inverse_rename(root, plan, preimage)
                restored = snapshot_apply_tree(root)
            except (ApplyFixtureError, OSError) as exc:
                recovery_error = str(exc)
                restored = snapshot_apply_tree(root)
                stop_after_cycle = True
            verdict, details = _classify_cycle(policy, preimage, post_apply, restored, plan, tool_success)
            if not declared_delta_valid:
                verdict = "FAILED_LOCKED"
            if recovery_error:
                verdict = "FAILED_LOCKED"
            cycle = {
                "cycle": cycle_index,
                "verdict": verdict,
                "business_tool_invocations": 1,
                "tool_success": tool_success,
                "declared_delta_valid": declared_delta_valid,
                "declared_delta_error": declared_delta_error,
                "relative_observed_delta": _relative_delta(preimage, post_apply),
                "collateral_paths": details["collateral"],
                "acl_added_rights": details["acl_added_rights"],
                "residual_fields": details["residual_fields"],
                "exact_identity_restored": restored == preimage,
                "independent_recovery_error": recovery_error,
                "tool_metadata_removed_during_cleanup": metadata_removed,
                "preimage_sha256": _canonical_hash(preimage),
                "post_apply_sha256": _canonical_hash(post_apply),
                "restored_sha256": _canonical_hash(restored),
            }
            cycles.append(cycle)
            shutil.rmtree(root.parent)

    normalized = [
        {
            "verdict": item["verdict"],
            "relative_observed_delta": item["relative_observed_delta"],
            "collateral_paths": item["collateral_paths"],
            "acl_added_rights": item["acl_added_rights"],
            "residual_fields": item["residual_fields"],
            "exact_identity_restored": item["exact_identity_restored"],
            "business_tool_invocations": item["business_tool_invocations"],
        }
        for item in cycles
    ]
    identical = len(normalized) == 5 and all(item == normalized[0] for item in normalized[1:])
    verdicts = {item["verdict"] for item in cycles}
    final_verdict = next(iter(verdicts)) if len(cycles) == 5 and len(verdicts) == 1 and identical else "FAILED_LOCKED"
    evidence = {
        "schema": "marvin.e7-apply-execution-result/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "observed_taxonomy_unchanged",
        "contract": "bulk_rename:apply",
        "source_commit": source_commit,
        "policy_sha256": _sha256(POLICY_PATH),
        "authorization_sha256": _sha256(AUTHORIZATION_PATH),
        "final_verdict": final_verdict,
        "runner_reclassified_taxonomy": False,
        "cycles_required": 5,
        "cycles_completed": len(cycles),
        "normalized_cycles_identical": identical,
        "business_tools_invoked": [{"tool": "bulk_rename", "action": "apply", "count": len(cycles)}],
        "all_other_business_tools_invoked": False,
        "fixture_contains_user_data": False,
        "persistent_host_paths_used": False,
        "cycles": cycles,
        "next_action": policy["verdict_actions"][final_verdict],
        "rollback": "delete_this_result_artifact; all temporary fixtures were independently restored and removed",
    }
    evidence["content_sha256"] = _canonical_hash(evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    temporary_output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_output, output)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    evidence = asyncio.run(run_campaign(arguments.output.resolve()))
    print(json.dumps({
        "final_verdict": evidence["final_verdict"],
        "cycles_completed": evidence["cycles_completed"],
        "content_sha256": evidence["content_sha256"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
