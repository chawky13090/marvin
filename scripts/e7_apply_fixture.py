"""Fixture indépendante pré-enregistrée pour le pilote E7 bulk_rename:apply."""

from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


class ApplyFixtureError(RuntimeError):
    pass


_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_GROUP_SECURITY_INFORMATION = 0x00000002
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SDDL_REVISION_1 = 1


def _require_windows() -> None:
    if os.name != "nt":
        raise ApplyFixtureError("apply_fixture_requires_windows")


def _security_descriptor(path: Path) -> str:
    _require_windows()
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    security_information = (
        _OWNER_SECURITY_INFORMATION
        | _GROUP_SECURITY_INFORMATION
        | _DACL_SECURITY_INFORMATION
    )
    advapi32.GetNamedSecurityInfoW.argtypes = (
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetNamedSecurityInfoW.restype = ctypes.c_uint32
    status = advapi32.GetNamedSecurityInfoW(
        str(path), _SE_FILE_OBJECT, security_information,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), None,
        ctypes.byref(descriptor),
    )
    if status:
        raise ApplyFixtureError(f"fixture_acl_read_failed:{status}")
    text = ctypes.c_wchar_p()
    length = ctypes.c_uint32()
    try:
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(ctypes.c_uint32),
        )
        advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = ctypes.c_int
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, _SDDL_REVISION_1, security_information,
            ctypes.byref(text), ctypes.byref(length),
        ):
            raise ApplyFixtureError(
                f"fixture_acl_sddl_failed:{ctypes.get_last_error()}"
            )
        return text.value or ""
    finally:
        if text:
            kernel32.LocalFree(text)
        if descriptor:
            kernel32.LocalFree(descriptor)


def protect_dacl_as_canary(path: Path) -> tuple[str, str]:
    """Protect the inherited DACL so rename can be distinguished from recreation."""
    _require_windows()
    resolved = path.resolve(strict=True)
    before = _security_descriptor(resolved)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    advapi32.GetNamedSecurityInfoW.argtypes = (
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetNamedSecurityInfoW.restype = ctypes.c_uint32
    status = advapi32.GetNamedSecurityInfoW(
        str(resolved), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), None,
        ctypes.byref(descriptor),
    )
    if status:
        raise ApplyFixtureError(f"fixture_acl_canary_read_failed:{status}")
    try:
        advapi32.SetNamedSecurityInfoW.argtypes = (
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        )
        advapi32.SetNamedSecurityInfoW.restype = ctypes.c_uint32
        status = advapi32.SetNamedSecurityInfoW(
            str(resolved), _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, dacl, None,
        )
        if status:
            raise ApplyFixtureError(f"fixture_acl_canary_write_failed:{status}")
    finally:
        if descriptor:
            ctypes.WinDLL("kernel32", use_last_error=True).LocalFree(descriptor)
    after = _security_descriptor(resolved)
    if after == before:
        raise ApplyFixtureError("fixture_acl_canary_not_discriminating")
    return before, after


def _relative_name(value: str) -> str:
    normalized = value.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if (
        not normalized
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.parts[0] in {".", ".."}
        or ":" in normalized
    ):
        raise ApplyFixtureError("fixture_rename_path_not_simple_relative")
    return candidate.as_posix()


def validate_simple_rename_plan(plan: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    if not plan:
        raise ApplyFixtureError("fixture_rename_plan_empty")
    pairs = tuple(sorted(
        ((_relative_name(source), _relative_name(target)) for source, target in plan.items()),
        key=lambda pair: pair[0].casefold(),
    ))
    source_keys = [source.casefold() for source, _target in pairs]
    target_keys = [target.casefold() for _source, target in pairs]
    if len(set(source_keys)) != len(source_keys) or len(set(target_keys)) != len(target_keys):
        raise ApplyFixtureError("fixture_rename_casefold_collision")
    if set(source_keys) & set(target_keys):
        raise ApplyFixtureError("fixture_rename_chain_or_cycle_forbidden")
    return pairs


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_apply_tree(root: Path) -> dict[str, dict[str, Any]]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir() or resolved.is_symlink():
        raise ApplyFixtureError("fixture_tree_invalid")
    snapshot: dict[str, dict[str, Any]] = {}
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            raise ApplyFixtureError("fixture_reparse_point_denied")
        stat = path.stat()
        relative = path.relative_to(resolved).as_posix()
        item: dict[str, Any] = {
            "kind": "directory" if path.is_dir() else "file",
            "size": stat.st_size,
            "device": stat.st_dev,
            "file_identity": stat.st_ino,
            "created_ns": stat.st_ctime_ns,
            "modified_ns": stat.st_mtime_ns,
            "acl_sddl": _security_descriptor(path),
        }
        if path.is_file():
            item["sha256"] = _sha256(path)
        snapshot[relative] = item
    return snapshot


def assert_declared_rename_delta(
    before: Mapping[str, Any], after: Mapping[str, Any], plan: Mapping[str, str],
) -> dict[str, Any]:
    pairs = validate_simple_rename_plan(plan)
    remaining_before = dict(before)
    remaining_after = dict(after)
    accepted: list[dict[str, str]] = []
    for source, target in pairs:
        source_value = remaining_before.pop(source, None)
        target_value = remaining_after.pop(target, None)
        if source_value is None or source_value != target_value:
            raise ApplyFixtureError("fixture_rename_delta_invalid")
        accepted.append({"source": source, "target": target})
    if remaining_before != remaining_after:
        raise ApplyFixtureError("fixture_rename_collateral_delta")
    return {"passed": True, "renames": accepted}


def restore_by_inverse_rename(
    root: Path,
    plan: Mapping[str, str],
    preimage: Mapping[str, Any],
) -> dict[str, Any]:
    resolved = root.resolve(strict=True)
    pairs = validate_simple_rename_plan(plan)
    for source, target in pairs:
        if source not in preimage or target in preimage:
            raise ApplyFixtureError("fixture_preimage_plan_mismatch")
        source_path = resolved / source
        target_path = resolved / target
        if source_path.exists() or not target_path.is_file() or target_path.is_symlink():
            raise ApplyFixtureError("fixture_inverse_rename_precondition_failed")
    for source, target in reversed(pairs):
        os.rename(resolved / target, resolved / source)
    restored = snapshot_apply_tree(resolved)
    if restored != dict(preimage):
        raise ApplyFixtureError("fixture_inverse_restore_identity_mismatch")
    return {"restored": True, "exact_identity": True, "renames": len(pairs)}


def build_apply_fixture(workspace: Path, cycle_index: int) -> dict[str, Any]:
    if cycle_index < 1 or cycle_index > 5:
        raise ApplyFixtureError("fixture_cycle_out_of_range")
    workspace = workspace.resolve(strict=True)
    root = workspace / f"cycle-{cycle_index:02d}" / "fixture-root"
    root.mkdir(parents=True, exist_ok=False)
    files = {
        "old-alpha.txt": b"fixture-alpha-v1\n",
        "old-beta.txt": b"fixture-beta-v1\n",
        "stable.txt": b"fixture-stable-v1\n",
    }
    for name, content in files.items():
        (root / name).write_bytes(content)
    _before_acl, canary_acl = protect_dacl_as_canary(root / "old-alpha.txt")
    preimage = snapshot_apply_tree(root)
    if preimage["old-alpha.txt"]["acl_sddl"] != canary_acl:
        raise ApplyFixtureError("fixture_acl_canary_capture_mismatch")
    if preimage["old-alpha.txt"]["acl_sddl"] == preimage["stable.txt"]["acl_sddl"]:
        raise ApplyFixtureError("fixture_acl_canary_not_distinct")
    plan = {"old-alpha.txt": "new-alpha.txt", "old-beta.txt": "new-beta.txt"}
    validate_simple_rename_plan(plan)
    return {
        "cycle_index": cycle_index,
        "root": root,
        "plan": plan,
        "preimage": preimage,
        "acl_canary": "old-alpha.txt",
    }
