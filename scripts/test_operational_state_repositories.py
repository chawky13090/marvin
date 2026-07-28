"""Régressions SQLite des repositories d'état opérationnel."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.cron_jobs import CronJobRepository
from repositories.network_inventory import NetworkInventoryRepository
from repositories.system_snapshots import SystemSnapshotRepository
from repositories.tool_templates import ToolTemplateRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "operational-state.db"
        scope = lambda: db(path)
        network = NetworkInventoryRepository(scope)
        snapshots = SystemSnapshotRepository(scope)
        templates = ToolTemplateRepository(scope)
        cron = CronJobRepository(scope)

        with patch(
            "repositories.network_inventory.uuid.uuid4",
            return_value="device-1",
        ):
            created = network.upsert("192.0.2.10", "AA:BB", "poste")
        assert created == {"id": "device-1", "new": True}
        assert network.upsert(" 192.0.2.10 ", " AA:BB ", "poste-2") == {
            "id": "device-1",
            "new": False,
        }
        assert network.set_notes(
            "device-1",
            custom_name="Atelier",
            notes="Poste de test",
        ) == {"success": True}
        devices = network.list_recent(days=0)
        assert len(devices) == 1
        assert devices[0]["hostname"] == "poste-2"
        assert devices[0]["custom_name"] == "Atelier"
        try:
            network.upsert(" ")
        except ValueError:
            pass
        else:
            raise AssertionError("Une adresse IP vide doit être refusée.")
        with patch(
            "repositories.network_inventory.uuid.uuid4",
            return_value="device-1",
        ):
            try:
                network.upsert("192.0.2.11", "AA:CC", "collision")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Une collision d'identifiant doit annuler l'upsert.")
        assert len(network.list_recent()) == 1

        with patch(
            "repositories.system_snapshots.uuid.uuid4",
            return_value="snapshot-1",
        ):
            snapshot = snapshots.save(42.5, 71.0, "C:", 3.0, 2)
        assert snapshot == {"id": "snapshot-1"}
        assert snapshots.list_recent(days=10_000)[0]["id"] == "snapshot-1"
        try:
            snapshots.save(float("nan"), 1, "C:", None, 0)
        except ValueError:
            pass
        else:
            raise AssertionError("Une métrique non finie doit être refusée.")
        try:
            snapshots.save(1, 1, "C:", None, -1)
        except ValueError:
            pass
        else:
            raise AssertionError("Un compteur d'erreurs négatif doit être refusé.")
        assert len(snapshots.list_recent()) == 1

        with patch(
            "repositories.tool_templates.uuid.uuid4",
            return_value="template-1",
        ):
            template = templates.save(
                "Ping",
                "net_ping",
                {"host": "équipement.local"},
                "Diagnostic",
                "réseau",
            )
        assert template["args"] == {"host": "équipement.local"}
        assert templates.get("template-1")["name"] == "Ping"
        assert len(templates.list(tool_name="net_ping", category="réseau")) == 1
        with db(path) as connection:
            connection.execute(
                "UPDATE tool_templates SET args = ? WHERE id = ?",
                ("{invalid", "template-1"),
            )
        assert templates.get("template-1")["args"] == {}
        with patch(
            "repositories.tool_templates.uuid.uuid4",
            return_value="template-1",
        ):
            try:
                templates.save("Collision", "net_ping", {})
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Une collision de modèle doit être annulée.")
        assert len(templates.list()) == 1

        with patch(
            "repositories.cron_jobs.uuid.uuid4",
            return_value="cron-1",
        ):
            job = cron.create(
                "Surveillance",
                "pc_health",
                {"mode": "court"},
                "every 5 minutes",
            )
        assert job["enabled"] is True and job["run_count"] == 0
        updated = cron.update(
            "cron-1",
            {
                "name": "Surveillance système",
                "args": {"mode": "complet"},
                "enabled": False,
                "run_count": True,
                "id": "injection-refusée",
            },
        )
        assert updated["id"] == "cron-1"
        assert updated["name"] == "Surveillance système"
        assert updated["args"] == {"mode": "complet"}
        assert updated["enabled"] is False and updated["run_count"] == 1
        assert cron.list(enabled_only=True) == []
        with db(path) as connection:
            connection.execute(
                "UPDATE cron_jobs SET args = ? WHERE id = ?",
                ("{invalid", "cron-1"),
            )
        assert cron.get("cron-1")["args"] == {}
        with patch(
            "repositories.cron_jobs.uuid.uuid4",
            return_value="cron-1",
        ):
            try:
                cron.create("Collision", "pc_health", {}, "daily")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Une collision cron doit être annulée.")
        assert len(cron.list()) == 1

        with db(path) as connection:
            indexes = {
                row[1]
                for row in connection.execute(
                    """SELECT type, name FROM sqlite_master
                       WHERE type = 'index'"""
                ).fetchall()
            }
        assert {
            "idx_network_devices_last_seen",
            "idx_system_snapshots_created",
            "idx_tool_templates_lookup",
            "idx_cron_enabled_next",
        }.issubset(indexes)

        templates.delete("template-1")
        cron.delete("cron-1")
        assert templates.get("template-1") is None
        assert cron.get("cron-1") is None

    import database
    from repositories import (
        cron_jobs,
        network_inventory,
        system_snapshots,
        tool_templates,
    )

    expected = {
        "upsert_network_device": network_inventory.upsert_network_device,
        "get_network_devices": network_inventory.get_network_devices,
        "set_network_device_notes": network_inventory.set_network_device_notes,
        "save_system_snapshot": system_snapshots.save_system_snapshot,
        "get_system_snapshots": system_snapshots.get_system_snapshots,
        "save_template": tool_templates.save_template,
        "list_templates": tool_templates.list_templates,
        "get_template": tool_templates.get_template,
        "delete_template": tool_templates.delete_template,
        "create_cron_job": cron_jobs.create_cron_job,
        "list_cron_jobs": cron_jobs.list_cron_jobs,
        "update_cron_job": cron_jobs.update_cron_job,
        "get_cron_job": cron_jobs.get_cron_job,
        "delete_cron_job": cron_jobs.delete_cron_job,
    }
    for name, function in expected.items():
        assert getattr(database, name) is function, name

    print(
        "Operational State Repositories OK - inventaire, snapshots, modèles, "
        "cron, JSON dégradé, bornes, transactions, index et façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
