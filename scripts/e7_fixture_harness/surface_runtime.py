from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping


class FixtureContractError(RuntimeError):
    pass


def _require_descendant(path: Path, workspace_root: Path) -> Path:
    resolved = path.resolve()
    workspace = workspace_root.resolve()
    if resolved == workspace or workspace not in resolved.parents:
        raise FixtureContractError("fixture_path_outside_workspace")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_tree(root: Path) -> dict[str, dict[str, Any]]:
    resolved = root.resolve()
    if not resolved.is_dir() or resolved.is_symlink():
        raise FixtureContractError("fixture_tree_invalid")
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(resolved.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            raise FixtureContractError("fixture_reparse_point_denied")
        relative = path.relative_to(resolved).as_posix()
        stat = path.stat()
        value: dict[str, Any] = {
            "kind": "directory" if path.is_dir() else "file",
            "size": stat.st_size,
            "mode": stat.st_mode,
        }
        if path.is_file():
            value["sha256"] = _sha256(path)
        result[relative] = value
    return result


def assert_zero_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    if dict(before) != dict(after):
        raise FixtureContractError("fixture_unexpected_delta")
    return {"passed": True, "delta": []}


def assert_rename_delta(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    expected: Mapping[str, str],
) -> dict[str, Any]:
    remaining_before = dict(before)
    remaining_after = dict(after)
    accepted: list[dict[str, str]] = []
    for source, target in sorted(expected.items()):
        source_value = remaining_before.pop(source, None)
        target_value = remaining_after.pop(target, None)
        if source_value is None or source_value != target_value:
            raise FixtureContractError("fixture_rename_delta_invalid")
        accepted.append({"source": source, "target": target})
    if remaining_before != remaining_after:
        raise FixtureContractError("fixture_rename_collateral_delta")
    return {"passed": True, "renames": accepted}


def restore_tree_from_preimage(
    root: Path, preimage: Path, expected_hash: str, *, workspace_root: Path,
) -> dict[str, Any]:
    root = _require_descendant(root, workspace_root)
    preimage = _require_descendant(preimage, workspace_root)
    if not preimage.is_dir() or preimage.is_symlink() or root == preimage:
        raise FixtureContractError("fixture_preimage_invalid")
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(preimage, root, symlinks=False)
    restored = snapshot_tree(root)
    actual = hashlib.sha256(json.dumps(restored, sort_keys=True).encode("utf-8")).hexdigest()
    if actual != expected_hash:
        raise FixtureContractError("fixture_restore_hash_mismatch")
    return {"restored": True, "snapshot_sha256": actual}


def snapshot_sqlite(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise FixtureContractError("fixture_sqlite_invalid")
    uri = resolved.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        row_counts = {
            name: connection.execute(f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34) * 2)}"').fetchone()[0]
            for name in tables
        }
        dump = "\n".join(connection.iterdump()).encode("utf-8")
    finally:
        connection.close()
    return {
        "integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
        "row_counts": row_counts,
        "logical_dump_sha256": hashlib.sha256(dump).hexdigest(),
        "file_sha256": _sha256(resolved),
    }


def restore_sqlite_from_preimage(
    target: Path, preimage: Path, expected_dump_hash: str, *, workspace_root: Path,
) -> dict[str, Any]:
    target = _require_descendant(target, workspace_root)
    preimage = _require_descendant(preimage, workspace_root)
    if not preimage.is_file() or preimage.is_symlink() or target == preimage:
        raise FixtureContractError("fixture_sqlite_preimage_invalid")
    temporary = target.with_suffix(target.suffix + ".restore.tmp")
    shutil.copy2(preimage, temporary)
    verified = snapshot_sqlite(temporary)
    if verified["logical_dump_sha256"] != expected_dump_hash:
        temporary.unlink(missing_ok=True)
        raise FixtureContractError("fixture_sqlite_restore_hash_mismatch")
    os.replace(temporary, target)
    return {"restored": True, **snapshot_sqlite(target)}


def snapshot_task_store(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise FixtureContractError("fixture_task_store_invalid")
    raw = resolved.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("tasks", []), list):
        raise FixtureContractError("fixture_task_store_schema_invalid")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "tasks": len(value.get("tasks", [])),
        "workers": len(value.get("workers", [])),
        "artifacts": len(value.get("artifacts", [])),
    }


def build_vm_execution_bundle(plan: Mapping[str, Any], *, clean_checkpoint_id: str) -> dict[str, Any]:
    if plan.get("isolation") != "disposable_windows_vm":
        raise FixtureContractError("fixture_vm_isolation_required")
    if not clean_checkpoint_id or ".." in clean_checkpoint_id or any(char in clean_checkpoint_id for char in "\\/:*?\"<>|"):
        raise FixtureContractError("fixture_checkpoint_invalid")
    return {
        "contract_id": plan["contract_id"],
        "checkpoint_id": clean_checkpoint_id,
        "execution_authorized": False,
        "host_execution_forbidden": True,
        "network": "isolated_or_fixture_endpoints_only",
        "permitted_executables": plan["permitted_executables"],
        "symbolic_payload": plan["symbolic_payload"],
        "surface_profile": plan["surface_profile"],
        "allowed_delta": plan["allowed_delta"],
        "forbidden_deltas": plan["forbidden_deltas"],
    }
