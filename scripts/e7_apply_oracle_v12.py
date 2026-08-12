"""Oracle indépendant du produit pour le rejeu E7 ``bulk_rename:apply`` v1.2."""
from __future__ import annotations

from typing import Any, Mapping

from e7_apply_fixture import ApplyFixtureError, restore_by_inverse_rename, snapshot_apply_tree


def relative_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[str]]:
    before_keys, after_keys = set(before), set(after)
    return {
        "removed": sorted(before_keys - after_keys),
        "added": sorted(after_keys - before_keys),
        "changed": sorted(key for key in before_keys & after_keys if before[key] != after[key]),
    }


def acl_added_rights(before_sddl: str, after_sddl: str) -> list[str]:
    def aces(value: str) -> set[str]:
        dacl = value.split("D:", 1)[1] if "D:" in value else ""
        return {f"({item}" for item in dacl.split("(")[1:]}
    return sorted(aces(after_sddl) - aces(before_sddl))


def verify_apply_delta(
    preimage: Mapping[str, Any], post_apply: Mapping[str, Any], plan: Mapping[str, str],
) -> dict[str, Any]:
    delta = relative_delta(preimage, post_apply)
    expected_removed, expected_added = sorted(plan), sorted(plan.values())
    valid = delta == {"removed": expected_removed, "added": expected_added, "changed": []}
    identity_preserved = all(preimage[source] == post_apply[target] for source, target in plan.items())
    return {"valid": valid and identity_preserved, "delta": delta, "identity_preserved": identity_preserved}


def restore_and_classify(
    root, plan: Mapping[str, str], preimage: Mapping[str, Any], *, tool_success: bool,
    allowed_residual_fields: frozenset[str] = frozenset({"file_identity", "created_ns"}),
) -> tuple[str, dict[str, Any]]:
    recovery_error = None
    try:
        restore_by_inverse_rename(root, plan, preimage)
    except (ApplyFixtureError, OSError) as exc:
        recovery_error = str(exc)
    restored = snapshot_apply_tree(root)
    exact = restored == dict(preimage)
    additions: dict[str, list[str]] = {}
    for relative in sorted(set(preimage) & set(restored)):
        added = acl_added_rights(preimage[relative]["acl_sddl"], restored[relative]["acl_sddl"])
        if added:
            additions[relative] = added
    residual_fields: set[str] = set()
    forbidden_difference = set(preimage) != set(restored)
    if not forbidden_difference:
        for relative in preimage:
            before_item, after_item = preimage[relative], restored[relative]
            for field in set(before_item) | set(after_item):
                if before_item.get(field) != after_item.get(field):
                    residual_fields.add(field)
                    if field not in allowed_residual_fields:
                        forbidden_difference = True
    if tool_success and exact and not additions and not recovery_error:
        verdict = "R_CONFIRMED"
    elif tool_success and not additions and not recovery_error and residual_fields and not forbidden_difference:
        verdict = "R_INVALID_C_CANDIDATE"
    else:
        verdict = "FAILED_LOCKED"
    return verdict, {
        "exact_identity_restored": exact,
        "acl_added_rights": additions,
        "independent_recovery_error": recovery_error,
        "residual_fields": sorted(residual_fields),
        "restored": restored,
    }
