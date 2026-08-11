from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "scripts" / "e7_fixture_harness"
OUTPUT = ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "pilot-fixture-harness-manifest.json"


def main() -> int:
    sources = sorted(PACKAGE.glob("*.py"))
    sources.extend(
        [
            ROOT / "scripts" / "test_e7_fixture_harness.py",
            ROOT / "scripts" / "test_e7_fixture_implementations.py",
            ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "direct-fixture-contracts.json",
            ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "direct-fixture-pilot.json",
        ]
    )
    value = {
        "schema": "marvin.pilot-fixture-harness-manifest/1.0",
        "status": "implementation_frozen_execution_locked",
        "fixture_plans": 6,
        "tool_execution_authorized": False,
        "host_execution_forbidden": True,
        "runtime_guard": {
            "process_isolation_required": True,
            "meta_path_allow_list": True,
            "stdlib_origin_validation": True,
            "dynamic_exec_compile_denied": True,
            "positive_canary_required": True,
            "negative_import_canary_required": True,
            "negative_dynamic_code_canary_required": True,
            "spawn_events_checked": ["subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn"],
            "undeclared_spawn_canary_required": True,
            "recursive_child_guard_canary_required": True,
            "python_child_requires_isolated_bootstrap": True,
            "system_binary_hash_is_evidence_not_acceptance": True,
            "windows_system_binary_requires_authenticode_and_publisher": True,
            "environment_allow_list_is_per_executable_contract": True,
            "attestation_runs_before_runtime_guard": True,
            "pre_guard_window_constrained_by_static_allow_list_and_manifest_hash": True,
            "system32_powershell_is_assumed_windows_trust_root": True,
            "powershell_attestation_script_is_manifest_hashed": True,
            "fixture_owned_script_hash_required": True,
            "audit_hook_never_installed_in_backend": True,
        },
        "files": {},
        "fixture_implementations": {
            "plans": 6,
            "local_surfaces_executable_on_synthetic_data_only": 4,
            "vm_execution_bundles_locked": 2,
            "marvin_tool_execution": False,
        },
        "rollback": "revert the atomic v2.619 commit; no Marvin tool or business fixture was executed",
    }
    for path in sources:
        relative = path.relative_to(ROOT).as_posix()
        value["files"][relative] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
    OUTPUT.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
