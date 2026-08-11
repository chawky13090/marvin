from __future__ import annotations

from typing import Any

from .pilot_fixtures import build_pilot_plans


def build_pilot_implementations() -> tuple[dict[str, Any], ...]:
    adapters = {
        "direct-bulk_rename-preview": {
            "prepare": "surface_runtime.snapshot_tree",
            "observe": "surface_runtime.snapshot_tree",
            "oracle": "surface_runtime.assert_zero_delta",
            "recover": None,
        },
        "direct-bulk_rename-apply": {
            "prepare": "surface_runtime.snapshot_tree",
            "observe": "surface_runtime.snapshot_tree",
            "oracle": "surface_runtime.assert_rename_delta",
            "recover": "surface_runtime.restore_tree_from_preimage",
        },
        "direct-note_delete-__default__": {
            "prepare": "surface_runtime.snapshot_sqlite",
            "observe": "surface_runtime.snapshot_sqlite",
            "oracle": "delta.note_selected_row_only",
            "recover": "surface_runtime.restore_sqlite_from_preimage",
        },
        "direct-long_task_start-__default__": {
            "prepare": "surface_runtime.snapshot_task_store",
            "observe": "surface_runtime.snapshot_task_store",
            "oracle": "delta.one_fixture_task_and_worker",
            "recover": "preimage.atomic_task_store_restore",
        },
        "direct-winget_uninstall-__default__": {
            "prepare": "surface_runtime.build_vm_execution_bundle",
            "observe": "offline_vm_inventory.software_scope",
            "oracle": "delta.selected_package_only",
            "recover": "hypervisor.clean_checkpoint_restore",
        },
        "direct-pc_process_kill-__default__": {
            "prepare": "surface_runtime.build_vm_execution_bundle",
            "observe": "offline_vm_inventory.process_scope",
            "oracle": "delta.exact_target_pid_and_no_collateral",
            "recover": "hypervisor.clean_checkpoint_teardown",
        },
    }
    implementations = []
    for plan in build_pilot_plans():
        adapter = adapters[plan["contract_id"]]
        implementations.append({
            "contract_id": plan["contract_id"],
            "e7_class": plan["e7_class"],
            "surface_profile": plan["surface_profile"],
            "isolation": plan["isolation"],
            "execution_authorized": False,
            "host_execution_forbidden": True,
            "adapter": adapter,
        })
    return tuple(implementations)
