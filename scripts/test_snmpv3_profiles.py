"""Contrats du coffre, du repository et de la surface LLM SNMPv3."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from repositories.snmp_profiles import SNMPProfileRepository  # noqa: E402
import snmp_profile_vault as vault  # noqa: E402
import tools  # noqa: E402


def main() -> None:
    secret_store: dict[str, str] = {}
    with patch.object(vault.dpapi_secret_store, "set_secret", side_effect=lambda key, value: secret_store.__setitem__(key, value)), patch.object(vault.dpapi_secret_store, "get_secret", side_effect=lambda key: secret_store.get(key)), patch.object(vault.dpapi_secret_store, "delete_secret", side_effect=lambda key: secret_store.pop(key, None)):
        with tempfile.TemporaryDirectory(prefix="marvin-snmpv3-") as temporary:
            path = Path(temporary) / "profiles.db"

            @contextmanager
            def scope():
                connection = sqlite3.connect(path)
                connection.row_factory = sqlite3.Row
                connection.execute("CREATE TABLE IF NOT EXISTS network_devices (id TEXT PRIMARY KEY, snmp_profile_id TEXT NOT NULL DEFAULT '')")
                try:
                    yield connection
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

            repository = SNMPProfileRepository(scope)
            created = repository.create(name="Cœur SNMP", username="marvin-ro", auth_key="auth-secret-123", priv_key="privacy-secret-123")
            assert "auth_key" not in json.dumps(created)
            full = repository.get(created["id"], include_secrets=True)
            assert full and full["auth_key"] == "auth-secret-123"
            assert repository.list()[0]["priv_protocol"] == "aes128"
            repository.delete(created["id"])
            assert not secret_store

    spec = next(item for item in tools.TOOLS_SPEC if item["function"]["name"] == "net_snmp_query")
    properties = spec["function"]["parameters"]["properties"]
    assert "community" not in properties and "auth_key" not in properties and "priv_key" not in properties
    assert "neighbors" in properties["action"]["enum"]
    assert tools.TOOLS_REGISTRY.keys() == {item["function"]["name"] for item in tools.TOOLS_SPEC}
    print("Profils SNMPv3 DPAPI et surface LLM : OK")


if __name__ == "__main__":
    main()
