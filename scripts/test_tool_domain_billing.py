"""Régressions déterministes du domaine d'outils Facturation."""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import billing


async def _run() -> None:
    for value in ("NaN", math.inf, "texte"):
        try:
            billing._finite_amount(value, field="montant")
        except ValueError:
            pass
        else:
            raise AssertionError("Un montant non fini ou invalide doit être refusé.")
    assert billing._finite_amount("12.345", field="montant") == 12.35

    original_get = billing.db.billing_invoice_get
    original_update = billing.db.billing_invoice_update
    updates: list[tuple[str, dict]] = []
    billing.db.billing_invoice_get = lambda _iid: {
        "id": "inv-1", "number": "F-1", "total_ttc": "120.00"
    }
    billing.db.billing_invoice_update = (
        lambda iid, data: updates.append((iid, data)) or {**data, "id": iid}
    )
    try:
        negative = await billing.execute_billing_invoice_mark_paid(
            {"invoice_id": "inv-1", "amount": -1}
        )
        assert "strictement positif" in negative["error"]
        excess = await billing.execute_billing_invoice_mark_paid(
            {"invoice_id": "inv-1", "amount": 121}
        )
        assert "dépasse" in excess["error"]
        partial = await billing.execute_billing_invoice_mark_paid(
            {"invoice_id": "inv-1", "amount": "60"}
        )
        assert partial["success"] is True
        assert updates[-1][1]["status"] == "partial"
        assert updates[-1][1]["amount_paid"] == 60.0
    finally:
        billing.db.billing_invoice_get = original_get
        billing.db.billing_invoice_update = original_update

    names = [
        name.removeprefix("execute_")
        for name in dir(billing)
        if name.startswith("execute_billing_")
    ]
    assert len(names) == 22
    for public_name in names:
        implementation = getattr(billing, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine Facturation OK")
