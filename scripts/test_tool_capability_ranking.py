"""Régressions du classement lexical portable des outils."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tool_capability_ranking import build_catalog, rank_capabilities


def _spec(name: str, description: str, properties: dict | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}},
        },
    }


def main() -> int:
    catalog = build_catalog([
        _spec("weather", "Prévisions météo pour une ville", {
            "location": {"type": "string", "description": "Ville recherchée"},
        }),
        _spec("email_list", "Liste les messages reçus dans les boîtes mail"),
        _spec("file_find", "Trouve un fichier sur le poste Windows ou Linux"),
        _spec("calculator", "Effectue un calcul mathématique exact"),
    ])
    assert rank_capabilities("prévisions météo pour Marseille", catalog)[0][0] == "weather"
    assert rank_capabilities("affiche les messages reçus", catalog)[0][0] == "email_list"
    assert rank_capabilities("retrouve un fichier de facture", catalog)[0][0] == "file_find"
    assert rank_capabilities("utilise calculator pour 17 fois 29", catalog)[0][0] == "calculator"
    assert rank_capabilities("bonjour comment vas tu", catalog) == []
    assert len(rank_capabilities("weather email file calculator", catalog, limit=2)) == 2
    print("Tool Capability Ranking OK - score, seuil, stabilité et borne.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
