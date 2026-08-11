from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
POLICY_PATH = BASE / "e7-preview-execution-policy-v1.1.json"
DEFAULT_OUTPUT = BASE / "e7-preview-execution-result.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from e7_fixture_harness.surface_runtime import assert_zero_delta, snapshot_tree  # noqa: E402
from tool_domains import filesystem as filesystem_domain  # noqa: E402


class CampaignRefused(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    return completed.stdout.strip()


def validate_policy(policy: dict[str, Any]) -> tuple[str, ...]:
    if policy.get("schema") != "marvin.e7-preview-execution-policy/1.1":
        raise CampaignRefused("e7_preview_policy_schema_invalid")
    if policy.get("authorized_contracts") != ["bulk_rename:preview"]:
        raise CampaignRefused("e7_preview_scope_not_unique")
    if policy.get("all_other_pilot_contracts_authorized") is not False:
        raise CampaignRefused("e7_other_pilots_not_locked")
    if policy.get("maximum_business_tool_invocations") != 1:
        raise CampaignRefused("e7_preview_invocation_budget_invalid")
    if policy.get("host_persistent_path_forbidden") is not True:
        raise CampaignRefused("e7_preview_host_path_not_forbidden")
    if policy.get("isolation") != "isolated_temp_volume":
        raise CampaignRefused("e7_preview_isolation_invalid")
    governed = tuple(policy.get("governed_source_hashes") or {})
    if not governed:
        raise CampaignRefused("e7_preview_sources_missing")
    for relative, expected in policy["governed_source_hashes"].items():
        path = ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            raise CampaignRefused(f"e7_preview_source_changed:{relative}")
    return governed


def _require_committed_sources(governed: tuple[str, ...]) -> str:
    _git("ls-files", "--error-unmatch", str(POLICY_PATH.relative_to(ROOT)))
    dirty = _git("diff", "--name-only", "--", *governed)
    staged = _git("diff", "--cached", "--name-only", "--", *governed)
    if dirty or staged:
        raise CampaignRefused("e7_preview_governed_sources_dirty")
    return _git("rev-parse", "HEAD")


async def run_campaign(output: Path) -> dict[str, Any]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    governed = validate_policy(policy)
    source_commit = _require_committed_sources(governed)
    if output.exists():
        raise CampaignRefused("e7_preview_result_already_exists")

    with tempfile.TemporaryDirectory(prefix="marvin-e7-preview-") as temporary:
        workspace = Path(temporary).resolve()
        fixture_root = workspace / "fixture-root"
        fixture_root.mkdir()
        (fixture_root / "old-A.txt").write_text("fixture-A", encoding="utf-8")
        (fixture_root / "stable.txt").write_text("stable", encoding="utf-8")
        before = snapshot_tree(fixture_root)

        def resolve_fixture_path(raw: str) -> str:
            resolved = Path(raw).resolve()
            if resolved == workspace or workspace not in resolved.parents:
                raise CampaignRefused("e7_preview_path_outside_temp_volume")
            return str(resolved)

        # Configuration locale au processus de campagne uniquement. Le resolver
        # refuse tout chemin qui ne descend pas du volume temporaire possede par
        # cette execution; il ne reutilise jamais le resolver de production.
        filesystem_domain.configure(resolve_path=resolve_fixture_path)

        result = await filesystem_domain.bulk_rename({
            "folder": str(fixture_root),
            "pattern": "old",
            "replace": "new",
            "action": "preview",
            "confirmed": False,
        })

        after = snapshot_tree(fixture_root)
        oracle = assert_zero_delta(before, after)
        preview = result.get("preview") if isinstance(result, dict) else None
        if result.get("requiresConfirmation") is not True or not isinstance(preview, list):
            raise CampaignRefused("e7_preview_contract_not_returned")
        if len(preview) != 1 or preview[0].get("old") != "old-A.txt" or preview[0].get("new") != "new-A.txt":
            raise CampaignRefused("e7_preview_projection_invalid")
        if any(path.name == "new-A.txt" for path in fixture_root.iterdir()):
            raise CampaignRefused("e7_preview_mutated_fixture")

        evidence = {
            "schema": "marvin.e7-preview-execution-result/1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "verified",
            "contract": "bulk_rename:preview",
            "e7_class": "N",
            "source_commit": source_commit,
            "policy_sha256": _sha256(POLICY_PATH),
            "business_tools_invoked": [{"tool": "bulk_rename", "action": "preview", "count": 1}],
            "all_other_pilot_contracts_invoked": False,
            "workspace": "ephemeral_temp_volume_removed_after_run",
            "fixture_contains_user_data": False,
            "confirmation_preview_returned": True,
            "preview_count": len(preview),
            "observable_mutation_count": len(oracle["delta"]),
            "before_snapshot_sha256": _snapshot_hash(before),
            "after_snapshot_sha256": _snapshot_hash(after),
            "snapshots_identical": before == after,
            "rollback_required": False,
            "rollback": "delete_this_evidence_file; fixture workspace was already removed",
        }

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
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
