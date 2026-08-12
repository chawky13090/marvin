from __future__ import annotations

import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import bulk_rename_rollback_store as store

def ops():
    return [{"old": "before.txt", "new": "after.txt", "temporary": ".marvin-test.tmp"}]

def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-rollback-store-") as temporary:
        base = Path(temporary); user_root = base / "user"; user_root.mkdir()
        central = base / "data" / "rollback" / "bulk-rename"
        path, payload = store.create(user_root, ops(), uuid.uuid4().hex, store_root=central)
        assert path.parent == central and not (user_root / ".marvin-rollback").exists()
        assert payload["schema_version"] == 2 and payload["owner_start_time"] > 0
        revision = payload["revision"]; store.heartbeat(path, payload, force=True)
        assert payload["revision"] == revision + 1
        try: store.save(path, payload, expected_revision=1)
        except store.RollbackStoreError: pass
        else: raise AssertionError("stale revision accepted")

        legacy_dir = user_root / ".marvin-rollback"; legacy_dir.mkdir()
        legacy_id = uuid.uuid4().hex; legacy = legacy_dir / f"bulk-rename-{legacy_id}.json"
        legacy.write_text(json.dumps({"version": 1, "tool": "bulk_rename", "status": "applied", "created_at": time.time(), "root": str(user_root), "operations": ops()}), encoding="utf-8")
        migrated = store.migrate_legacy_for_root(user_root, store_root=central)
        assert len(migrated) == 1 and not legacy.exists()
        _, loaded, loaded_root = store.load(migrated[0], store_root=central)
        assert loaded_root == user_root.resolve() and loaded["legacy"]["read_compatibility_until"] > time.time()
        restored_legacy = Path(store.rollback_legacy_migration(migrated[0], store_root=central))
        assert restored_legacy.is_file() and not Path(migrated[0]).exists()
        migrated = store.migrate_legacy_for_root(user_root, store_root=central)
        assert len(migrated) == 1

        stale_id = uuid.uuid4().hex
        stale_path, stale = store.create(user_root, ops(), stale_id, store_root=central)
        stale.update({"owner_pid": 999999, "owner_start_time": 1.0, "heartbeat_at": 1.0})
        store.save(stale_path, stale, expected_revision=stale["revision"])
        result = store.rotate(store_root=central, now=time.time())
        assert stale_path.name in result["abandoned"] and any(item["run_id"] == stale_id for item in result["alerts"])
        abandoned = json.loads(stale_path.read_text(encoding="utf-8")); future = abandoned["abandoned_at"] + store.ABANDONED_RETENTION_SECONDS + 1
        store.rotate(store_root=central, now=future); assert stale_path.exists()
        abandoned["notification_acknowledged_at"] = time.time(); store.save(stale_path, abandoned, expected_revision=abandoned["revision"])
        store.rotate(store_root=central, now=future); assert not stale_path.exists()

        unrelated = base / "unrelated" / ".marvin-rollback"; unrelated.mkdir(parents=True)
        marker = unrelated / "ignored.json"; marker.write_text("{}", encoding="utf-8")
        store.migrate_legacy_for_root(user_root, store_root=central); assert marker.exists()
    source = (ROOT / "backend" / "tool_domains" / "filesystem.py").read_text(encoding="utf-8")
    assert 'root / ".marvin-rollback" / f"bulk-rename-' not in source
    assert "rollback_store.heartbeat" in source
    print("Bulk rename rollback store OK - central store, lease, migration and retention verified.")
    return 0

if __name__ == "__main__": raise SystemExit(main())
