from __future__ import annotations

import sqlite3
import sys
import tempfile
import importlib.util
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from db_migrations import MIGRATIONS, apply_migrations, current_schema_version

spec = importlib.util.spec_from_file_location(
    "rollback_infrastructure_asset_registry",
    ROOT / "scripts" / "rollback-infrastructure-asset-registry.py",
)
assert spec and spec.loader
rollback_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollback_module)
rollback = rollback_module.rollback


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-assets-rollback-") as temporary:
        database = Path(temporary) / "secretary.db"
        with closing(sqlite3.connect(database)) as connection:
            # Ce test historique vérifie exclusivement la descente v8 -> v7.
            # La descente v9 -> v8 dispose de son propre contrat séparé.
            apply_migrations(connection, MIGRATIONS[:8])
            connection.execute(
                """INSERT INTO network_devices
                   (id,ip,custom_name,asset_type,vendor,management_protocols)
                   VALUES('asset-1','192.0.2.10','Cœur','switch','Cisco','["snmpv3"]')"""
            )
            connection.commit()
            assert current_schema_version(connection) == 8
        result = rollback(database, confirmed=True)
        assert result["schema_version"] == 7
        assert Path(result["backup"]).is_file()
        with closing(sqlite3.connect(database)) as connection:
            assert current_schema_version(connection) == 7
            row = connection.execute(
                "SELECT ip,custom_name FROM network_devices WHERE id='asset-1'"
            ).fetchone()
            assert row == ("192.0.2.10", "Cœur")
            columns = {
                item[1] for item in connection.execute("PRAGMA table_info(network_devices)")
            }
            assert "asset_type" not in columns
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        try:
            rollback(database, confirmed=False)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Le rollback sans confirmation devait être refusé.")
    print("Rollback registre d'actifs : OK")


if __name__ == "__main__":
    main()
