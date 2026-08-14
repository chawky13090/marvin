"""Canaris positifs et négatifs de la vue canonique présentée au LLM."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tool_canonical_facade import build_canonical_tool_view, classify_canonical_intent
from tools import TOOLS_SPEC


NAMES = {str(item["function"]["name"]) for item in TOOLS_SPEC}


def _decision(text: str) -> str | None:
    value = classify_canonical_intent(text, public_tool_names=NAMES)
    return value.capability_id if value else None


def main() -> None:
    assert len(NAMES) == len(TOOLS_SPEC) == 364
    positive = {
        "application.launch": [
            "Ouvre l'application Bloc-notes.",
            "Lance le logiciel Paint sur ce PC.",
        ],
        "software.search": [
            "Cherche un logiciel installable nommé VLC.",
            "Recherche l'application PowerToys dans Winget.",
        ],
        "software.install": [
            "Installe le logiciel VLC sur ce PC.",
            "Ajoute l'application PowerToys avec Winget.",
        ],
        "software.list_installed": [
            "Liste les logiciels installés sur ce PC.",
            "Affiche les applications installées.",
        ],
        "software.list_upgrades": [
            "Liste les mises à jour disponibles.",
            "Affiche les updates possibles pour les logiciels.",
        ],
        "software.upgrade": [
            "Mets le logiciel VLC à jour.",
            "Upgrade tous les paquets installés.",
        ],
        "software.uninstall": [
            "Désinstalle le logiciel VLC.",
            "Retire l'application PowerToys de ce PC.",
        ],
    }
    for capability, queries in positive.items():
        for query in queries:
            assert _decision(query) == capability, (capability, query, _decision(query))

    negatives = [
        "Comment ouvrir une application Windows ?",
        "Quelle commande lance le Bloc-notes ?",
        "Ouvre le fichier C:\\Temp\\rapport.pdf.",
        "Ouvre le dossier Documents.",
        "Ouvre la page web https://example.test.",
        "Ouvre les paramètres Windows.",
        "Lance l'application Paint puis désinstalle VLC.",
        "Installe puis désinstalle le logiciel VLC.",
        "Utilise explicitement pc_app_launch pour Paint.",
        "Recherche mes fichiers PDF.",
        "Liste les processus actifs.",
        "Envoie un courriel au client.",
        "Explique la gestion des logiciels Windows.",
        "Donne-moi la commande Winget pour installer VLC.",
    ]
    for query in negatives:
        assert _decision(query) is None, (query, _decision(query))

    original = copy.deepcopy(TOOLS_SPEC)
    app_view = build_canonical_tool_view(
        "Lance l'application Bloc-notes.", TOOLS_SPEC, all_tool_names=NAMES, enabled=True
    )
    assert app_view.active and app_view.status == "active"
    assert [item["function"]["name"] for item in app_view.tools] == [
        "windows_task", "tool_search"
    ]
    action = app_view.tools[0]["function"]["parameters"]["properties"]["action"]
    assert action["enum"] == ["application.launch"]
    assert "action" in app_view.tools[0]["function"]["parameters"]["required"]
    assert TOOLS_SPEC == original

    install_view = build_canonical_tool_view(
        "Installe le logiciel VLC sur ce PC.", TOOLS_SPEC, all_tool_names=NAMES, enabled=True
    )
    assert [item["function"]["name"] for item in install_view.tools] == [
        "winget_install", "winget_search", "tool_search"
    ]
    assert TOOLS_SPEC == original

    missing_view = build_canonical_tool_view(
        "Lance l'application Bloc-notes.",
        [item for item in TOOLS_SPEC if item["function"]["name"] == "tool_search"],
        all_tool_names=NAMES,
        enabled=True,
    )
    assert missing_view.active and missing_view.status == "canonical_executor_missing"
    assert [item["function"]["name"] for item in missing_view.tools] == ["tool_search"]

    disabled = build_canonical_tool_view(
        "Lance l'application Bloc-notes.", TOOLS_SPEC, all_tool_names=NAMES
    )
    assert not disabled.active and disabled.status == "disabled_pending_validation"
    assert list(disabled.tools) == TOOLS_SPEC

    agent_source = (ROOT / "backend/agent.py").read_text(encoding="utf-8")
    facade_source = (ROOT / "backend/tool_canonical_facade.py").read_text(encoding="utf-8")
    assert "_build_canonical_tool_view(" in agent_source
    assert "benchmarks" not in facade_source
    assert "stage-b-b1-result" not in facade_source
    assert "pc_get_real_paths" not in facade_source
    print("Canonical tool facade OK - 14 positive canaries, 14 negative canaries, 364 tools preserved.")


if __name__ == "__main__":
    main()
