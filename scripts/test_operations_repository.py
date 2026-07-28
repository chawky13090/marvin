"""Régressions SQLite du repository des contrôles opérationnels."""

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
from repositories.operations import OperationsRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "operations.db"
        repository = OperationsRepository(connection_scope=lambda: db(path))
        with db(path) as connection:
            repository.ensure_schema(connection)

        with patch(
            "repositories.operations.uuid.uuid4",
            return_value="check-1",
        ):
            check = repository.check_create(
                {
                    "intervention_id": "intervention-1",
                    "check_type": "precheck",
                    "title": "Préparation",
                }
            )
        assert check["id"] == "check-1" and check["items"] == []

        with patch(
            "repositories.operations.uuid.uuid4",
            return_value="item-1",
        ):
            item = repository.item_create(
                "check-1",
                {
                    "label": "Sauvegarde",
                    "severity": "critical",
                    "order_index": 1,
                    "auto_command": "Get-Date",
                },
            )
        assert item["check_id"] == "check-1"
        try:
            repository.item_create("absent", {"label": "Interdit"})
        except ValueError:
            pass
        else:
            raise AssertionError("Un point orphelin doit être refusé.")

        with patch(
            "repositories.operations.uuid.uuid4",
            return_value="result-1",
        ):
            result = repository.result_set(
                "check-1",
                "item-1",
                {"status": "ok", "actual_value": "Présente"},
            )
        assert result["id"] == "result-1"
        updated_result = repository.result_set(
            "check-1",
            "item-1",
            {"status": "warning", "notes": "À renouveler"},
        )
        assert updated_result["id"] == "result-1"
        assert updated_result["status"] == "warning"
        try:
            repository.result_set("check-1", "item-absent", {"status": "ok"})
        except ValueError:
            pass
        else:
            raise AssertionError("Un résultat incohérent doit être refusé.")

        with patch(
            "repositories.operations.uuid.uuid4",
            return_value="evidence-1",
        ):
            evidence = repository.evidence_create(
                {
                    "check_id": "check-1",
                    "item_id": "item-1",
                    "result_id": "result-1",
                    "intervention_id": "intervention-1",
                    "evidence_type": "log",
                    "content": "preuve métier complète",
                }
            )
        assert evidence["content"] == "preuve métier complète"
        assert repository.evidence_list("intervention-1", "check-1")[0][
            "id"
        ] == "evidence-1"
        full = repository.check_get("check-1")
        assert full["items"][0]["result"]["id"] == "result-1"
        assert full["results"][0]["status"] == "warning"
        assert full["evidence"][0]["content"] == "preuve métier complète"

        changed = repository.check_update(
            "check-1",
            {
                "status": "partial",
                "summary": "Une alerte",
                "check_type": "postcheck",
            },
        )
        assert changed["status"] == "partial"
        assert changed["check_type"] == "precheck"
        assert repository.check_list(
            "intervention-1",
            "precheck",
        )[0]["id"] == "check-1"

        with patch(
            "repositories.operations.uuid.uuid4",
            return_value="check-1",
        ):
            try:
                repository.check_create({"title": "Collision"})
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Une collision doit annuler la checklist.")
        assert len(repository.check_list()) == 1

        with patch(
            "repositories.operations.uuid.uuid4",
            return_value="check-2",
        ):
            repository.check_create(
                {
                    "intervention_id": "intervention-1",
                    "check_type": "postcheck",
                    "title": "Validation",
                }
            )
        try:
            repository.evidence_create(
                {
                    "check_id": "check-2",
                    "item_id": "item-1",
                    "evidence_type": "text",
                }
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Une preuve croisée entre checklists doit être refusée.")

        repository.check_delete("check-1")
        assert repository.check_get("check-1") is None
        assert repository.evidence_list(check_id="check-1") == []
        with db(path) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM ops_check_items WHERE check_id = ?",
                    ("check-1",),
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM ops_check_results WHERE check_id = ?",
                    ("check-1",),
                ).fetchone()[0]
                == 0
            )

    import database
    from repositories import operations

    names = (
        "ops_check_create",
        "ops_check_get",
        "ops_check_list",
        "ops_check_update",
        "ops_check_delete",
        "ops_item_create",
        "ops_result_set",
        "ops_evidence_create",
        "ops_evidence_list",
    )
    for name in names:
        assert getattr(database, name) is getattr(operations, name), name

    print(
        "Operations Repository OK - checks, items, résultats, preuves métier, "
        "cohérence, cascade, rollback et 9 façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
