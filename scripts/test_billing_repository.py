"""Régressions SQLite du repository de facturation."""

from __future__ import annotations

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
from repositories.billing import BillingRepository


NOW = datetime(2026, 7, 28, 12, 0, 0)


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "billing.db"
        repository = BillingRepository(
            connection_scope=lambda: db(path),
            clock=lambda: NOW,
        )
        with db(path) as connection:
            repository.ensure_schema(connection)
        assert len(repository.catalog_list()) == 19

        with patch("repositories.billing.uuid.uuid4", return_value="client-1"):
            client = repository.client_create(
                {
                    "name": "KOIOS Test",
                    "client_type": "pme",
                    "contact_email": "test@example.invalid",
                    "previous_amount": "120.50",
                }
            )
        assert client["id"] == "client-1"
        assert client["previous_amount"] == 120.5
        client = repository.client_update(
            "client-1",
            {"notes": "Validation", "id": "injection-refusée"},
        )
        assert client["id"] == "client-1" and client["notes"] == "Validation"
        assert repository.client_list("pme")[0]["id"] == "client-1"

        first_items = [
            {"name": "Service", "qty": 2, "cost": 30, "total": 200},
            {"name": "Option", "qty": 1, "cost": 10, "total": 50},
        ]
        with patch("repositories.billing.uuid.uuid4", return_value="quote-high"):
            high = repository.quote_create(
                {
                    "client_id": "client-1",
                    "number": "DEV-2026-0042",
                    "items": first_items,
                    "tva_rate": 10,
                }
            )
        assert high["total_ht"] == 250
        assert high["total_ttc"] == 275
        assert high["cost"] == 70
        assert high["margin"] == 180
        assert high["margin_pct"] == 72
        assert high["items"] == first_items

        with patch("repositories.billing.uuid.uuid4", return_value="quote-43"):
            quote = repository.quote_create(
                {
                    "client_id": "client-1",
                    "items": [{"total": 100, "cost": 20, "qty": 1}],
                    "tva_rate": 20,
                }
            )
        assert quote["number"] == "DEV-2026-0043"
        quote = repository.quote_update("quote-43", {"tva_rate": 5})
        assert quote["total_ht"] == 100
        assert quote["total_ttc"] == 105
        assert quote["items"][0]["total"] == 100
        assert repository.quote_list("client-1", "draft")
        with db(path) as connection:
            connection.execute(
                "UPDATE billing_quotes SET items_json = ? WHERE id = ?",
                ("{invalid", "quote-43"),
            )
        assert repository.quote_get("quote-43")["items"] == []

        with patch("repositories.billing.uuid.uuid4", return_value="quote-43"):
            try:
                repository.quote_create(
                    {
                        "client_id": "client-1",
                        "items": [{"total": 1}],
                    }
                )
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("La collision devis doit annuler la transaction.")
        with patch("repositories.billing.uuid.uuid4", return_value="quote-44"):
            after_collision = repository.quote_create(
                {"client_id": "client-1", "items": []}
            )
        assert after_collision["number"] == "DEV-2026-0044"
        with ThreadPoolExecutor(max_workers=4) as executor:
            concurrent_quotes = list(
                executor.map(
                    lambda index: repository.quote_create(
                        {
                            "client_id": "client-1",
                            "title": f"Concurrent {index}",
                            "items": [],
                        }
                    ),
                    range(8),
                )
            )
        concurrent_numbers = {item["number"] for item in concurrent_quotes}
        assert len(concurrent_numbers) == 8
        assert concurrent_numbers == {
            f"DEV-2026-{number:04d}" for number in range(45, 53)
        }

        with patch("repositories.billing.uuid.uuid4", return_value="service-1"):
            service = repository.catalog_create(
                {
                    "name": "Service expert",
                    "category": "Validation",
                    "unit": "heure",
                    "price_basic": 80,
                    "price_standard": 100,
                    "price_premium": 130,
                    "cost": 35,
                    "time_hours": 1,
                }
            )
        assert service["id"] == "service-1"
        assert any(
            item["id"] == "service-1"
            for item in repository.catalog_list("Validation")
        )
        try:
            repository.catalog_create(
                {"name": "Invalide", "price_basic": float("nan")}
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Un prix non fini doit être refusé.")

        with patch("repositories.billing.uuid.uuid4", return_value="invoice-1"):
            invoice = repository.invoice_create(
                {
                    "client_id": "client-1",
                    "quote_id": "quote-43",
                    "total_ht": 100,
                    "tva_rate": 20,
                    "items": [{"name": "Service", "total": 100}],
                    "payment_terms": 30,
                    "issue_date": "2026-06-01",
                    "status": "sent",
                }
            )
        assert invoice["number"] == "FAC-2026-0001"
        assert invoice["total_ttc"] == 120
        assert invoice["due_date"] == "2026-07-01"
        assert invoice["items"][0]["name"] == "Service"
        listed_invoice = repository.invoice_list("client-1", "sent")[0]
        assert listed_invoice["is_overdue"] is True
        invoice = repository.invoice_update(
            "invoice-1",
            {"amount_paid": 60, "status": "partial", "client_id": "interdit"},
        )
        assert invoice["amount_paid"] == 60
        assert invoice["client_id"] == "client-1"
        try:
            repository.invoice_update("invoice-1", {"amount_paid": 121})
        except ValueError:
            pass
        else:
            raise AssertionError("Un trop-perçu doit être refusé.")
        assert repository.invoice_get("invoice-1")["amount_paid"] == 60

        with patch("repositories.billing.uuid.uuid4", return_value="contract-1"):
            contract = repository.contract_create(
                {
                    "client_id": "client-1",
                    "name": "MCO",
                    "amount_ht": 500,
                    "period": "mois",
                }
            )
        assert contract["id"] == "contract-1"
        assert repository.contract_list("client-1")[0]["amount_ht"] == 500
        assert repository.contract_list()[0]["client_name"] == "KOIOS Test"

        with db(path) as connection:
            indexes = {
                row[1]
                for row in connection.execute(
                    "SELECT type, name FROM sqlite_master WHERE type = 'index'"
                ).fetchall()
            }
        assert {
            "idx_quotes_client",
            "idx_quotes_status",
            "idx_catalog_category",
            "idx_invoices_client",
            "idx_contracts_client",
        }.issubset(indexes)

        repository.catalog_delete("service-1")
        repository.invoice_delete("invoice-1")
        repository.quote_delete("quote-high")
        repository.quote_delete("quote-43")
        repository.quote_delete("quote-44")
        repository.client_delete("client-1")
        assert repository.client_get("client-1") is None
        assert repository.invoice_get("invoice-1") is None
        assert repository.contract_list("client-1") == []

    import database
    from repositories import billing

    names = (
        "billing_client_create",
        "billing_client_get",
        "billing_client_list",
        "billing_client_update",
        "billing_client_delete",
        "billing_quote_create",
        "billing_quote_get",
        "billing_quote_list",
        "billing_quote_update",
        "billing_quote_delete",
        "billing_catalog_list",
        "billing_catalog_create",
        "billing_catalog_delete",
        "billing_invoice_create",
        "billing_invoice_list",
        "billing_invoice_get",
        "billing_invoice_update",
        "billing_invoice_delete",
        "billing_contract_create",
        "billing_contract_list",
    )
    for name in names:
        assert getattr(database, name) is getattr(billing, name), name

    print(
        "Billing Repository OK - clients, devis, séquences, totaux, catalogue, "
        "factures, paiements, contrats, cascade, rollback et 20 façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
