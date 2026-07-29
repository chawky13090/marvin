"""Contrats de découverte progressive des outils Marvin."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from capability_catalog import CapabilityCatalog  # noqa: E402
from tools import TOOLS_REGISTRY, TOOLS_SPEC, execute_tool_search  # noqa: E402


def main() -> None:
    catalog = CapabilityCatalog(TOOLS_SPEC)
    assert len(catalog) == len(TOOLS_SPEC) == len(TOOLS_REGISTRY)

    exact = catalog.search("email_send", limit=5)
    assert exact["candidates"][0]["name"] == "email_send"
    assert exact["advisory_only"] is True

    docker = catalog.search("inspecter les conteneurs docker et lire leurs logs", limit=12)
    assert docker["count"] <= 12
    assert len({item["name"] for item in docker["candidates"]}) == docker["count"]

    specs = catalog.exact_specifications(["email_send", "email_send", "missing"])
    assert [item["function"]["name"] for item in specs] == ["email_send"]
    assert catalog.exact_specifications(["missing"]) == []

    try:
        catalog.search("")
    except ValueError:
        pass
    else:
        raise AssertionError("Une recherche vide doit être refusée.")

    result = asyncio.run(execute_tool_search("recherche web publique", 8))
    assert result["catalog_size"] == len(TOOLS_SPEC)
    assert result["count"] <= 8

    print(
        f"OK - {len(catalog)} capacités dérivées du registre, "
        "recherche consultative et schémas différés exacts"
    )


if __name__ == "__main__":
    main()
