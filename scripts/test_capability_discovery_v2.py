"""Évaluation reproductible de la découverte progressive des outils Marvin."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from capability_catalog import CapabilityCatalog  # noqa: E402
from capability_discovery import DISCOVERY_SCHEMA_VERSION  # noqa: E402
from tool_router import tool_index_fingerprint  # noqa: E402
from tools import TOOLS_SPEC  # noqa: E402


CASES = (
    ("Aspire toutes les pages du site example.com.", "web_site_crawl"),
    ("Explore entièrement ce site et conserve ses pages.", "web_site_crawl"),
    ("Cherche sur Internet plusieurs sources concernant Ollama.", "web_search"),
    ("Ouvre précisément cette URL qui utilise JavaScript.", "web_browser_open"),
    ("Fais une recherche Web documentée et synthétise les sources.", "web_research"),
    ("Réalise une étude Web exhaustive avec beaucoup de sources.", "web_deep_research"),
    ("Ouvre ce fichier PDF pour que je puisse le voir.", "pc_open_file"),
    ("Analyse le contenu de ce PDF et résume-le.", "pdf_read"),
    ("Lis le contenu de ce fichier texte.", "file_read"),
    ("Retrouve le fichier facture-2026 par son nom.", "file_find"),
    ("Cherche le mot erreur dans tous les fichiers de ce dossier.", "file_search_text"),
    (
        "Retrouve le document qui parle du contrat Koios sans connaître son emplacement.",
        "system_search_content",
    ),
    ("Crée un dossier projet Loïc dans la barre latérale.", "project_create"),
    ("Crée un répertoire physique C:\\Temp\\validation.", "file_create_folder"),
    ("Crée le dossier exact demandé pour la fixture Forge.", "windows_task"),
    ("Liste les processus actifs puis trie-les par mémoire.", "windows_task"),
    ("Ferme le processus VMware et vérifie qu'il est arrêté.", "windows_task"),
    ("Affiche la date et l'heure actuelles.", "datetime_info"),
    ("Recherche les logiciels installables avec Winget.", "winget_search"),
    ("Liste le contenu du dossier distant par SSH.", "ssh_list_dir"),
    ("Affiche les caractéristiques matérielles de ce PC.", "pc_hardware_specs"),
    ("Envoie un courriel au client.", "email_send"),
    ("Prépare seulement un brouillon de réponse au courriel.", "email_draft_reply"),
    ("Liste les conversations du projet courant.", "conversation_list"),
    ("Déplace cette conversation dans le projet Support.", "conversation_move"),
    ("Crée une nouvelle tâche pour demain.", "task_create"),
    ("Ajoute une note personnelle avec ce texte.", "note_create"),
)


def _rank(catalog: CapabilityCatalog, query: str, limit: int = 5) -> list[str]:
    return [item["name"] for item in catalog.search(query, limit=limit)["candidates"]]


def test_quality() -> None:
    catalog = CapabilityCatalog(TOOLS_SPEC, enhanced=True)
    registered = {
        specification["function"]["name"]
        for specification in TOOLS_SPEC
    }
    hits_at_5 = 0
    reciprocal_rank = 0.0
    for query, expected in CASES:
        assert expected in registered, f"Capacité de référence absente: {expected}"
        ranked = _rank(catalog, query)
        if expected in ranked:
            hits_at_5 += 1
            reciprocal_rank += 1.0 / (ranked.index(expected) + 1)
    recall_at_5 = hits_at_5 / len(CASES)
    mrr = reciprocal_rank / len(CASES)
    assert recall_at_5 >= 0.95, f"Recall@5 insuffisant: {recall_at_5:.3f}"
    assert mrr >= 0.72, f"MRR insuffisant: {mrr:.3f}"


def test_profiles_and_rollback() -> None:
    enhanced = CapabilityCatalog(TOOLS_SPEC, enhanced=True)
    result = enhanced.search("aspirer toutes les pages d'un site", limit=5)
    assert result["discovery_schema"] == DISCOVERY_SCHEMA_VERSION
    crawl = next(item for item in result["candidates"] if item["name"] == "web_site_crawl")
    assert crawl["title"]
    assert crawl["aliases"]
    assert crawl["use_when"]
    assert crawl["do_not_use_when"]
    assert "web_browser_open" in crawl["related_tools"]

    legacy = CapabilityCatalog(TOOLS_SPEC, enhanced=False).search(
        "aspirer toutes les pages d'un site",
        limit=5,
    )
    assert legacy["discovery_schema"] == "legacy"
    assert all(not item["aliases"] for item in legacy["candidates"])

    typed = _rank(
        enhanced,
        "Crée le dossier exact demandé pour la fixture Forge.",
        limit=5,
    )
    assert "windows_task" in typed
    assert typed.index("windows_task") < typed.index("computer_control") \
        if "computer_control" in typed else True
    assert "computer_control" not in typed

    visual = _rank(
        enhanced,
        "Clique dans l'interface Windows après une capture d'écran.",
        limit=10,
    )
    assert "computer_control" in visual


def test_index_invalidation() -> None:
    sample = [{
        "type": "function",
        "function": {
            "name": "demo",
            "description": "Première description",
            "parameters": {"type": "object", "properties": {}},
        },
    }]
    before = tool_index_fingerprint(sample)
    changed_description = [{
        **sample[0],
        "function": {
            **sample[0]["function"],
            "description": "Description différente",
        },
    }]
    assert tool_index_fingerprint(changed_description) != before
    changed_parameter = [{
        **sample[0],
        "function": {
            **sample[0]["function"],
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Cible exacte"},
                },
            },
        },
    }]
    assert tool_index_fingerprint(changed_parameter) != before


if __name__ == "__main__":
    test_quality()
    test_profiles_and_rollback()
    test_index_invalidation()
    print(f"Capability Discovery v2 OK - {len(CASES)} intentions évaluées")
