from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from e7_fixture_harness import build_pilot_implementations, build_pilot_plans
from e7_fixture_harness.surface_runtime import (
    FixtureContractError,
    assert_rename_delta,
    assert_zero_delta,
    build_vm_execution_bundle,
    restore_sqlite_from_preimage,
    restore_tree_from_preimage,
    snapshot_sqlite,
    snapshot_task_store,
    snapshot_tree,
)


def _snapshot_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def main() -> int:
    plans = {plan["contract_id"]: plan for plan in build_pilot_plans()}
    implementations = {item["contract_id"]: item for item in build_pilot_implementations()}
    assert set(plans) == set(implementations)
    assert len(implementations) == 6
    for contract_id, implementation in implementations.items():
        plan = plans[contract_id]
        assert implementation["e7_class"] == plan["e7_class"]
        assert implementation["surface_profile"] == plan["surface_profile"]
        assert implementation["execution_authorized"] is False
        assert implementation["host_execution_forbidden"] is True

    with tempfile.TemporaryDirectory(prefix="marvin-e7-fixture-") as temporary:
        root = Path(temporary)
        tree = root / "tree"
        tree.mkdir()
        (tree / "old-A.txt").write_text("A", encoding="utf-8")
        (tree / "stable.txt").write_text("stable", encoding="utf-8")
        before = snapshot_tree(tree)
        assert_zero_delta(before, snapshot_tree(tree))
        preimage = root / "tree-preimage"
        preimage.mkdir()
        for path in tree.iterdir():
            (preimage / path.name).write_bytes(path.read_bytes())
        (tree / "old-A.txt").rename(tree / "new-A.txt")
        after = snapshot_tree(tree)
        assert_rename_delta(before, after, {"old-A.txt": "new-A.txt"})
        restore_tree_from_preimage(tree, preimage, _snapshot_digest(before), workspace_root=root)
        assert snapshot_tree(tree) == before

        database = root / "fixture.db"
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE notes(id TEXT PRIMARY KEY, content TEXT NOT NULL)")
            connection.execute("INSERT INTO notes VALUES('fixture-note-A17', 'fixture')")
            connection.commit()
        finally:
            connection.close()
        database_preimage = root / "fixture-preimage.db"
        database_preimage.write_bytes(database.read_bytes())
        db_before = snapshot_sqlite(database)
        connection = sqlite3.connect(database)
        try:
            connection.execute("DELETE FROM notes WHERE id='fixture-note-A17'")
            connection.commit()
        finally:
            connection.close()
        assert snapshot_sqlite(database)["row_counts"]["notes"] == 0
        restored = restore_sqlite_from_preimage(
            database, database_preimage, db_before["logical_dump_sha256"], workspace_root=root,
        )
        assert restored["logical_dump_sha256"] == db_before["logical_dump_sha256"]

        task_store = root / "tasks.json"
        task_store.write_text('{"tasks":[],"workers":[],"artifacts":[]}', encoding="utf-8")
        assert snapshot_task_store(task_store)["tasks"] == 0

        for contract_id in (
            "direct-winget_uninstall-__default__",
            "direct-pc_process_kill-__default__",
        ):
            bundle = build_vm_execution_bundle(plans[contract_id], clean_checkpoint_id="clean-A17")
            assert bundle["execution_authorized"] is False
            assert bundle["host_execution_forbidden"] is True
        try:
            build_vm_execution_bundle(plans["direct-winget_uninstall-__default__"], clean_checkpoint_id="..\\host")
        except FixtureContractError:
            pass
        else:
            raise AssertionError("Un identifiant de checkpoint dangereux a été accepté.")
        try:
            restore_tree_from_preimage(root.parent / "outside", preimage, _snapshot_digest(before), workspace_root=root)
        except FixtureContractError:
            pass
        else:
            raise AssertionError("Une restauration hors racine de fixture a été acceptée.")

    print("E7 Fixture Implementations OK - 6 contrats, snapshots/oracles/recovery et bundles VM verrouillés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
