"""Contrat du registre portable d'actifs réseau et serveurs."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from repositories.network_inventory import NetworkInventoryRepository  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-assets-") as temporary:
        database_path = Path(temporary) / "assets.db"

        @contextmanager
        def scope():
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

        repository = NetworkInventoryRepository(scope)
        created = repository.register(
            "SW-CORE-01.example.lan",
            custom_name="Cœur de réseau",
            asset_type="switch",
            vendor="Cisco",
            model="C9300",
            os_family="network",
            role="core",
            site="Paris",
            management_protocols=["SSH", "SNMPv3", "NETCONF"],
            tags=["production", "critique"],
            ssh_connection_id="e9dc030c-9e92-45e8-a9c9-64dc5b94d351",
        )
        assert created["success"] is True
        device = created["device"]
        assert device["ip"] == "sw-core-01.example.lan"
        assert device["asset_type"] == "switch"
        assert device["management_protocols"] == ["netconf", "snmpv3", "ssh"]
        assert device["source"] == "manual"
        assert device["enabled"] is True

        updated = repository.set_metadata(
            device["id"], notes="Configuration sauvegardée hors équipement.", enabled=False
        )["device"]
        assert updated["enabled"] is False
        assert updated["notes"].startswith("Configuration")

        listed = repository.list_recent(30)
        assert len(listed) == 1
        assert listed[0]["tags"] == ["critique", "production"]
        serialized = json.dumps(listed, ensure_ascii=False)
        for forbidden_value in ("mot-de-passe", "private-key-data", "community-secret"):
            assert forbidden_value not in serialized

        for invalid in ("https://switch.local/path", "bad host name", ""):
            try:
                repository.register(invalid, asset_type="switch")
            except ValueError:
                pass
            else:
                raise AssertionError(f"Adresse invalide acceptée : {invalid!r}")

        try:
            repository.register("192.0.2.10", password="mot-de-passe")
        except ValueError as exc:
            assert "secrets" in str(exc)
        else:
            raise AssertionError("Un secret a été accepté dans le registre portable.")

        try:
            repository.set_metadata(device["id"], notes="community=private-value")
        except ValueError as exc:
            assert "secret" in str(exc)
        else:
            raise AssertionError("Un secret a été accepté dans une note d'actif.")

        try:
            repository.set_metadata(device["id"], management_protocols=["telnet"])
        except ValueError as exc:
            assert "non pris en charge" in str(exc)
        else:
            raise AssertionError("Un protocole de gestion non autorisé a été accepté.")

    print("Registre portable d'actifs infrastructure : OK")


if __name__ == "__main__":
    main()
