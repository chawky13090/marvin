from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"


DEFINITIONS: list[tuple[str, str, str, str, str, str, str]] = [
    ("note_delete", "__default__", "R", "database_scope", "isolated_sqlite_clone", "database_preimage_restore", "note row and related constraints"),
    ("task_delete", "__default__", "R", "database_scope", "isolated_sqlite_clone", "database_preimage_restore", "task row and related constraints"),
    ("memory_delete", "__default__", "R", "database_scope", "isolated_memory_store", "database_and_vector_preimage_restore", "memory record and vector index entry"),
    ("project_delete", "__default__", "R", "database_scope", "isolated_sqlite_clone", "database_preimage_restore", "project row while conversations remain unchanged"),
    ("bulk_rename", "apply", "R", "filesystem_scope", "isolated_temp_volume", "filesystem_preimage_restore", "declared rename set only"),
    ("bulk_rename", "rollback", "R", "filesystem_scope", "isolated_temp_volume", "filesystem_preimage_restore", "prebuilt post-apply tree and manifest"),
    ("tweak_debloat_remove", "__default__", "C", "software_scope", "disposable_windows_vm", "hypervisor_checkpoint_restore", "declared fixture package set only"),
    ("winget_uninstall", "__default__", "C", "software_scope", "disposable_windows_vm", "hypervisor_checkpoint_restore", "one fixture package removed"),
    ("winget_install", "__default__", "C", "software_scope", "disposable_windows_vm", "hypervisor_checkpoint_restore", "one pinned fixture package added"),
    ("winget_upgrade", "__default__", "C", "software_scope", "disposable_windows_vm", "hypervisor_checkpoint_restore", "one pinned fixture package upgraded"),
    ("itsm_ticket_create", "__default__", "C", "external_record_scope", "isolated_protocol_double", "protocol_double_reset", "one test ticket and one provider receipt"),
    ("system_restore_point", "__default__", "C", "windows_system_scope", "disposable_windows_vm", "hypervisor_checkpoint_restore", "one named restore point"),
    ("vm_lab_install", "install", "C", "windows_system_scope", "nested_virtualization_test_host", "hypervisor_checkpoint_restore", "one fixture VM definition"),
    ("pc_pull_ollama_model", "__default__", "C", "model_scope", "isolated_ollama_instance", "ollama_data_preimage_restore", "one fixture model tag and its blobs"),
    ("code_workspace_start", "__default__", "C", "workspace_scope", "isolated_workspace_runtime", "workspace_preimage_restore", "one fixture mission and worktree"),
    ("code_workspace_control", "resume", "C", "workspace_scope", "isolated_workspace_runtime", "workspace_preimage_restore", "one prebuilt paused fixture mission"),
    ("code_workspace_control", "cancel", "C", "workspace_scope", "isolated_workspace_runtime", "workspace_preimage_restore", "one prebuilt running fixture mission"),
    ("long_task_start", "__default__", "C", "workspace_scope", "isolated_task_runtime", "workspace_preimage_restore", "one fixture long task and worker"),
    ("pc_process_kill", "__default__", "I", "process_scope", "disposable_windows_vm", "hypervisor_checkpoint_teardown", "exact fixture PID only"),
    ("email_send", "__default__", "I", "external_message_scope", "isolated_smtp_protocol_double", "protocol_double_teardown", "one declared SMTP envelope only"),
    ("bulk_rename", "preview", "N", "no_mutation_scope", "isolated_temp_volume", "not_applicable", "zero observable mutation"),
    ("vm_lab_install", "status", "N", "no_mutation_scope", "nested_virtualization_test_host", "not_applicable", "zero observable mutation"),
]

SURFACE_FIELDS = {
    "database_scope": ["selected_rows", "foreign_keys", "row_counts", "logical_dump_hash"],
    "filesystem_scope": ["tree", "path_identity", "sha256", "size", "timestamps", "acl"],
    "software_scope": ["package_inventory", "files", "services", "scheduled_tasks", "user_settings"],
    "external_record_scope": ["record_id", "record_fields", "audit_history", "provider_receipt"],
    "windows_system_scope": ["services", "registry", "scheduled_tasks", "packages", "restore_points", "disk_usage"],
    "model_scope": ["ollama_inventory", "blob_inventory", "disk_usage", "running_models"],
    "workspace_scope": ["mission_state", "job_state", "worktree_hash", "artifacts", "background_workers"],
    "process_scope": ["pid", "process_table", "child_processes", "dependent_services", "listening_sockets"],
    "external_message_scope": ["sender", "recipients", "content_hash", "attachments_hash", "provider_receipt"],
    "no_mutation_scope": ["input_snapshot", "output_hash", "system_delta"],
}

PILOT = [
    ("bulk_rename", "preview"),
    ("bulk_rename", "apply"),
    ("note_delete", "__default__"),
    ("long_task_start", "__default__"),
    ("winget_uninstall", "__default__"),
    ("pc_process_kill", "__default__"),
]


def _contract(item: tuple[str, str, str, str, str, str, str]) -> dict[str, Any]:
    tool, action, class_, surface, isolation, recovery, target = item
    pair = f"{tool}:{action}"
    fixture_builder = "prebuilt_bulk_rename_rollback_fixture" if pair == "bulk_rename:rollback" else f"fixture_builder.{surface}"
    expected_fidelity = {"R": "exact_identity", "C": "functional_with_declared_residual_loss", "I": "not_restorable_confinement_required", "N": "no_mutation"}[class_]
    residual_loss = "none" if class_ in {"R", "N"} else ("intrinsic_volatile_or_external_state" if class_ == "I" else "declared_by_frozen_e7_classification")
    return {
        "id": f"direct-{tool}-{action.replace('_', '-')}",
        "tool": tool,
        "action": action,
        "class": class_,
        "surface_profile": surface,
        "execution_authorized": False,
        "host_execution_forbidden": True,
        "input_fixture": {
            "kind": "symbolic_valid_payload",
            "target": target,
            "contains_secret": False,
            "contains_real_recipient_or_tenant": False,
        },
        "isolation": {
            "kind": isolation,
            "clean_checkpoint_required": isolation in {"disposable_windows_vm", "nested_virtualization_test_host"},
            "network": "isolated_or_fixture_endpoints_only",
        },
        "setup": {
            "component": fixture_builder,
            "uses_tool_registry": False,
            "public_tools_used": [],
            "calls_system_under_test": False,
            "preimage_required": class_ in {"R", "C", "I"},
        },
        "observation": {
            "component": f"fixture_observer.{surface}",
            "fields": SURFACE_FIELDS[surface],
            "capture_before_and_after": True,
            "uses_tool_registry": False,
            "public_tools_used": [],
        },
        "oracle": {
            "component": f"fixture_oracle.{surface}",
            "independent_from_executor": True,
            "uses_tool_registry": False,
            "public_tools_used": [],
            "pass_condition": "expected_delta_only_and_no_forbidden_delta",
            "false_success_forbidden": True,
        },
        "recovery": {
            "component": f"fixture_recovery.{recovery}",
            "mechanism": recovery,
            "independent_from_executor": True,
            "uses_tool_registry": False,
            "public_tools_used": [],
            "expected_fidelity": expected_fidelity,
            "residual_loss": residual_loss,
        },
        "allowed_delta": target,
        "forbidden_deltas": ["undeclared_target", "unrelated_process_service_socket", "unrelated_file_database_or_provider_record"],
        "timeout_seconds": 300 if isolation in {"disposable_windows_vm", "nested_virtualization_test_host"} else 90,
    }


def _dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contracts = [_contract(item) for item in DEFINITIONS]
    contract_doc = {
        "schema": "marvin.direct-fixture-contracts/1.0",
        "status": "designed_frozen_execution_locked",
        "source_taxonomy_manifest": "e7-freeze-manifest.json",
        "source_fixture_strategy_manifest": "h7-fixture-strategy-manifest.json",
        "tool_execution_authorized": False,
        "host_execution_forbidden": True,
        "invariants": {
            "fixture_builder_never_calls_system_under_test": True,
            "system_under_test_never_verifies_or_restores_itself": True,
            "no_public_marvin_tool_in_setup_oracle_or_recovery": True,
            "oracle_and_recovery_use_fixture_harness_only": True,
            "R_requires_exact_identity_restore": True,
            "C_requires_declared_residual_loss": True,
            "I_requires_predeclared_observation_surface_and_confinement": True,
            "N_requires_zero_observable_mutation": True,
            "bulk_rename_apply_never_uses_bulk_rename_rollback_for_recovery": True,
            "bulk_rename_rollback_fixture_is_constructed_without_bulk_rename_apply": True,
        },
        "contracts": contracts,
    }
    pilot_pairs = {f"{tool}:{action}" for tool, action in PILOT}
    pilot = {
        "schema": "marvin.direct-fixture-pilot/1.0",
        "status": "designed_frozen_execution_locked",
        "purpose": "validate_fixture_method_across_six_distinct_surfaces_and_four_e7_classes",
        "tool_execution_authorized": False,
        "host_execution_forbidden": True,
        "contracts": [
            {"tool": c["tool"], "action": c["action"], "class": c["class"], "surface_profile": c["surface_profile"]}
            for c in contracts if f'{c["tool"]}:{c["action"]}' in pilot_pairs
        ],
    }
    contracts_path = BASE / "direct-fixture-contracts.json"
    pilot_path = BASE / "direct-fixture-pilot.json"
    _dump(contracts_path, contract_doc)
    _dump(pilot_path, pilot)
    sources = [
        BASE / "e7-classification.json",
        BASE / "fixture-strata-policy.json",
        BASE / "h7-fixture-strategy-manifest.json",
        contracts_path,
        pilot_path,
    ]
    manifest = {
        "schema": "marvin.direct-fixture-freeze-manifest/1.0",
        "status": "frozen_before_fixture_implementation",
        "fixture_implementation_authorized": True,
        "tool_execution_authorized": False,
        "host_execution_forbidden": True,
        "files": {str(path.relative_to(BASE)).replace(os.sep, "/"): {"sha256": _sha(path), "bytes": path.stat().st_size} for path in sources},
        "rollback": "revert the atomic v2.615 commit; no fixture or tool execution and no persistent data mutation occurred",
    }
    _dump(BASE / "direct-fixture-freeze-manifest.json", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
