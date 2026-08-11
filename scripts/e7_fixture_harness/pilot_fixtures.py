from __future__ import annotations

from .core import FixturePlan, component, validate_plan


COMMON_FORBIDDEN = (
    "undeclared_target",
    "unrelated_process_service_socket",
    "unrelated_file_database_or_provider_record",
)


PILOT_FIXTURES = (
    FixturePlan(
        contract_id="direct-bulk_rename-preview",
        tool="bulk_rename", action="preview", e7_class="N", surface_profile="no_mutation_scope",
        isolation="isolated_temp_volume",
        symbolic_payload={"folder": "fixture-root", "pattern": "old", "replace": "new", "action": "preview"},
        setup=component("fixture_builder.no_mutation_scope", "temp_volume", "create_tree", "snapshot_input"),
        observer=component("fixture_observer.no_mutation_scope", "filesystem_snapshot", "before", "after"),
        oracle=component("fixture_oracle.no_mutation_scope", "snapshot_diff", "assert_zero_delta"),
        recovery=component("fixture_recovery.not_applicable", "none", "verify_no_recovery_needed"),
        allowed_delta="zero observable mutation", forbidden_deltas=COMMON_FORBIDDEN,
    ),
    FixturePlan(
        contract_id="direct-bulk_rename-apply",
        tool="bulk_rename", action="apply", e7_class="R", surface_profile="filesystem_scope",
        isolation="isolated_temp_volume",
        symbolic_payload={"folder": "fixture-root", "pattern": "old", "replace": "new", "action": "apply", "confirmed": True},
        setup=component("fixture_builder.filesystem_scope", "temp_volume", "create_tree", "capture_preimage"),
        observer=component("fixture_observer.filesystem_scope", "filesystem_snapshot", "tree", "sha256", "acl"),
        oracle=component("fixture_oracle.filesystem_scope", "snapshot_diff", "assert_declared_renames_only"),
        recovery=component("fixture_recovery.filesystem_preimage_restore", "filesystem_preimage", "exact"),
        allowed_delta="declared rename set only", forbidden_deltas=COMMON_FORBIDDEN,
    ),
    FixturePlan(
        contract_id="direct-note_delete-__default__",
        tool="note_delete", action="__default__", e7_class="R", surface_profile="database_scope",
        isolation="isolated_sqlite_clone",
        symbolic_payload={"id": "fixture-note-A17", "confirmed": True},
        setup=component("fixture_builder.database_scope", "sqlite_fixture", "create_schema", "insert_fixture_row", "logical_dump"),
        observer=component("fixture_observer.database_scope", "sqlite_readonly", "rows", "foreign_keys", "dump_hash"),
        oracle=component("fixture_oracle.database_scope", "sqlite_readonly", "assert_selected_row_only"),
        recovery=component("fixture_recovery.database_preimage_restore", "sqlite_transaction", "exact"),
        allowed_delta="note row and related constraints", forbidden_deltas=COMMON_FORBIDDEN,
    ),
    FixturePlan(
        contract_id="direct-long_task_start-__default__",
        tool="long_task_start", action="__default__", e7_class="C", surface_profile="workspace_scope",
        isolation="isolated_task_runtime",
        symbolic_payload={"goal": "fixture goal", "steps": ["fixture step"], "confirmed": True},
        setup=component("fixture_builder.workspace_scope", "task_store_double", "create_empty_store", "snapshot_workers"),
        observer=component("fixture_observer.workspace_scope", "task_store_reader", "task_state", "worker_state", "artifact_hash"),
        oracle=component("fixture_oracle.workspace_scope", "task_store_reader", "assert_one_task_and_worker"),
        recovery=component("fixture_recovery.workspace_preimage_restore", "task_store_snapshot", "functional", "declare_audit_residue"),
        allowed_delta="one fixture long task and worker", forbidden_deltas=COMMON_FORBIDDEN,
    ),
    FixturePlan(
        contract_id="direct-winget_uninstall-__default__",
        tool="winget_uninstall", action="__default__", e7_class="C", surface_profile="software_scope",
        isolation="disposable_windows_vm",
        symbolic_payload={"id": "Marvin.Fixture.Package", "confirmed": True},
        setup=component("fixture_builder.software_scope", "vm_checkpoint_adapter", "verify_clean_checkpoint", "inventory_package"),
        observer=component("fixture_observer.software_scope", "offline_vm_inventory", "packages", "files", "services", "settings"),
        oracle=component("fixture_oracle.software_scope", "offline_vm_inventory", "assert_selected_package_only"),
        recovery=component("fixture_recovery.hypervisor_checkpoint_restore", "vm_checkpoint_adapter", "functional", "declare_settings_loss"),
        allowed_delta="one fixture package removed", forbidden_deltas=COMMON_FORBIDDEN,
        permitted_executables=({
            "id": "windows.winget",
            "identity": "windows_signed_system_binary",
            "resolved_path_required": True,
            "authenticode_status": "Valid",
            "publisher": "Microsoft Corporation",
            "shell": False,
            "arguments_schema": "winget_uninstall_fixture_v1",
            "hash_is_evidence_not_acceptance": True,
            "allowed_environment": (
                "LOCALAPPDATA", "PATH", "ProgramFiles", "ProgramFiles(x86)",
                "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "WINDIR",
            ),
        },),
    ),
    FixturePlan(
        contract_id="direct-pc_process_kill-__default__",
        tool="pc_process_kill", action="__default__", e7_class="I", surface_profile="process_scope",
        isolation="disposable_windows_vm",
        symbolic_payload={"pid": 4242, "confirmed": True},
        setup=component("fixture_builder.process_scope", "vm_process_fixture", "start_fixture_process", "capture_full_surface"),
        observer=component("fixture_observer.process_scope", "vm_process_inventory", "processes", "children", "services", "sockets"),
        oracle=component("fixture_oracle.process_scope", "surface_diff", "assert_exact_target_pid_only"),
        recovery=component("fixture_recovery.hypervisor_checkpoint_teardown", "vm_checkpoint_adapter", "confinement", "teardown"),
        allowed_delta="exact fixture PID only", forbidden_deltas=COMMON_FORBIDDEN,
        permitted_executables=({
            "id": "fixture.python_guarded_child",
            "identity": "parent_python_interpreter",
            "isolated_flag": "-I",
            "entrypoint": "guard_subprocess.py",
            "script_mode_only": True,
            "forbid_dash_c": True,
            "forbid_dash_m": True,
            "fixture_script_sha256_required": True,
            "shell": False,
        },),
    ),
)


def build_pilot_plans() -> tuple[dict, ...]:
    for plan in PILOT_FIXTURES:
        validate_plan(plan)
    return tuple(plan.to_dict() for plan in PILOT_FIXTURES)
