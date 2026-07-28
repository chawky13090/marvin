"""Régressions SQLite du repository de documentation technique."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.documentation import DocumentationRepository
from repositories.documentation_templates import DEFAULT_DOCUMENT_TEMPLATES


NOW = datetime(2026, 7, 28, 12, 0, 0)


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "documentation.db"
        repository = DocumentationRepository(
            connection_scope=lambda: db(path),
            clock=lambda: NOW,
        )
        with db(path) as connection:
            repository.ensure_schema(connection)
        templates = repository.template_list()
        assert len(templates) == len(DEFAULT_DOCUMENT_TEMPLATES) == 7
        template_payload = json.dumps(
            DEFAULT_DOCUMENT_TEMPLATES,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        assert hashlib.sha256(template_payload).hexdigest() == (
            "3d019841ddc4fb48a591b56b4f6abba3d61b4ef977c6387043773a3bf8d22986"
        )
        assert {item["doc_type"] for item in templates} == {
            item[0] for item in DEFAULT_DOCUMENT_TEMPLATES
        }
        assert all(item["content_md"].strip() for item in templates)

        with patch(
            "repositories.documentation.uuid.uuid4",
            return_value="asset-1",
        ):
            asset = repository.asset_create(
                {
                    "name": "Serveur test",
                    "asset_type": "server",
                    "client_id": "client-1",
                    "criticality": "high",
                }
            )
        assert asset["id"] == "asset-1"
        assert repository.asset_list("client-1")[0]["name"] == "Serveur test"

        with patch(
            "repositories.documentation.uuid.uuid4",
            return_value="intervention-high",
        ):
            high = repository.intervention_create(
                {
                    "number": "INT-2026-0042",
                    "title": "Référence",
                    "asset_ids": ["asset-1"],
                    "tags": ["réseau"],
                }
            )
        assert high["asset_ids"] == ["asset-1"]
        with patch(
            "repositories.documentation.uuid.uuid4",
            return_value="intervention-43",
        ):
            intervention = repository.intervention_create(
                {
                    "title": "Incident réseau",
                    "client_id": "client-1",
                    "asset_ids": ["asset-1"],
                    "screenshots": ["capture.png"],
                    "attachments": ["preuve.txt"],
                    "tags": ["réseau", "incident"],
                    "duration_minutes": 15,
                    "rgpd_relevant": True,
                }
            )
        assert intervention["number"] == "INT-2026-0043"
        assert intervention["screenshots"] == ["capture.png"]
        assert intervention["rgpd_relevant"] == 1
        intervention = repository.intervention_update(
            "intervention-43",
            {
                "status": "resolved",
                "duration_minutes": 30,
                "tags": ["résolu"],
                "id": "injection-refusée",
            },
        )
        assert intervention["status"] == "resolved"
        assert intervention["tags"] == ["résolu"]
        assert intervention["id"] == "intervention-43"
        assert repository.intervention_list(
            "client-1",
            "resolved",
            limit=0,
        )[0]["id"] == "intervention-43"
        try:
            repository.intervention_update(
                "intervention-43",
                {"duration_minutes": -1},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Une durée négative doit être refusée.")

        with patch(
            "repositories.documentation.uuid.uuid4",
            return_value="intervention-43",
        ):
            try:
                repository.intervention_create({"title": "Collision"})
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("La collision doit annuler la séquence.")
        with patch(
            "repositories.documentation.uuid.uuid4",
            return_value="intervention-44",
        ):
            after_collision = repository.intervention_create(
                {"title": "Après rollback"}
            )
        assert after_collision["number"] == "INT-2026-0044"

        with ThreadPoolExecutor(max_workers=4) as executor:
            concurrent = list(
                executor.map(
                    lambda index: repository.intervention_create(
                        {"title": f"Concurrent {index}"}
                    ),
                    range(4),
                )
            )
        assert {item["number"] for item in concurrent} == {
            f"INT-2026-{number:04d}" for number in range(45, 49)
        }

        with patch(
            "repositories.documentation.uuid.uuid4",
            return_value="document-1",
        ):
            document = repository.document_create(
                {
                    "intervention_id": "intervention-43",
                    "client_id": "client-1",
                    "doc_type": "report",
                    "format": "pdf",
                    "title": "Rapport",
                    "size_bytes": 120,
                    "version": 2,
                    "tags": ["preuve"],
                }
            )
        assert document["tags"] == ["preuve"]
        assert repository.document_list(
            "intervention-43",
            "client-1",
            "report",
        )[0]["version"] == 2
        with db(path) as connection:
            connection.execute(
                "UPDATE doc_documents SET tags = ? WHERE id = ?",
                ("{invalid", "document-1"),
            )
        assert repository.document_list(intervention_id="intervention-43")[0][
            "tags"
        ] == []
        try:
            repository.document_create(
                {"doc_type": "custom", "title": "Invalide", "size_bytes": -1}
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Une taille négative doit être refusée.")

        report_template = repository.template_list("report")[0]
        usage_before = report_template["usage_count"]
        repository.template_use(report_template["id"])
        assert (
            repository.template_get(report_template["id"])["usage_count"]
            == usage_before + 1
        )

        with db(path) as connection:
            connection.execute(
                "UPDATE doc_interventions SET tags = ? WHERE id = ?",
                ("{invalid", "intervention-43"),
            )
        assert repository.intervention_get("intervention-43")["tags"] == []

        repository.intervention_delete("intervention-43")
        assert repository.intervention_get("intervention-43") is None
        assert repository.document_list(intervention_id="intervention-43") == []
        repository.asset_delete("asset-1")
        assert repository.asset_list("client-1") == []

    import database
    from repositories import documentation

    names = (
        "doc_intervention_create",
        "doc_intervention_get",
        "doc_intervention_list",
        "doc_intervention_update",
        "doc_intervention_delete",
        "doc_document_create",
        "doc_document_list",
        "doc_document_delete",
        "doc_template_list",
        "doc_template_get",
        "doc_template_use",
        "doc_asset_create",
        "doc_asset_list",
        "doc_asset_delete",
    )
    for name in names:
        assert getattr(database, name) is getattr(documentation, name), name

    print(
        "Documentation Repository OK - modèles, actifs, interventions, séquences, "
        "documents, JSON, concurrence, cascade, rollback et 14 façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
