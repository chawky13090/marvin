"""Vérifie la descente SQLite v9 SNMPv3 sur une base jetable."""
from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rollback-snmpv3-profiles.py"
spec = importlib.util.spec_from_file_location("rollback_snmpv3", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-snmp-rollback-") as temporary:
        database = Path(temporary) / "test.db"
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript("""
                CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,checksum TEXT,applied_at TEXT);
                INSERT INTO schema_migrations VALUES(9,'snmpv3-profiles-and-asset-link','test','now');
                CREATE TABLE snmp_profiles(id TEXT PRIMARY KEY);
                CREATE TABLE network_devices(
                    id TEXT PRIMARY KEY,ip TEXT NOT NULL,mac TEXT DEFAULT '',hostname TEXT DEFAULT '',custom_name TEXT DEFAULT '',notes TEXT DEFAULT '',
                    first_seen TEXT DEFAULT '',last_seen TEXT DEFAULT '',asset_type TEXT DEFAULT 'unknown',vendor TEXT DEFAULT '',model TEXT DEFAULT '',
                    os_family TEXT DEFAULT '',role TEXT DEFAULT '',site TEXT DEFAULT '',management_protocols TEXT DEFAULT '[]',tags TEXT DEFAULT '[]',
                    ssh_connection_id TEXT DEFAULT '',snmp_profile_id TEXT DEFAULT '',enabled INTEGER DEFAULT 1,source TEXT DEFAULT '',updated_at TEXT DEFAULT '',
                    UNIQUE(mac,ip));
                INSERT INTO network_devices(id,ip,snmp_profile_id) VALUES('asset','192.0.2.10','');
                PRAGMA user_version=9;
            """)
            connection.commit()
        result = module.rollback(database, confirmed=True)
        assert result["schema_version"] == 8 and Path(result["backup"]).is_file()
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
            assert "snmp_profile_id" not in {row[1] for row in connection.execute("PRAGMA table_info(network_devices)")}
            assert connection.execute("SELECT ip FROM network_devices").fetchone()[0] == "192.0.2.10"
    print("Rollback des profils SNMPv3 : OK")


if __name__ == "__main__":
    main()
