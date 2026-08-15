"""Canaries for the text-only retrospective software coverage classifier."""

from __future__ import annotations

import json
from pathlib import Path

import tool_selection_v16_coverage as coverage


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "benchmarks/tool-selection/v1.6/measurement-strategy-preregistration.json").read_text(encoding="utf-8"))


def main() -> None:
    cases = {
        "Installe VLC": "software.install",
        "instaler le logiciel 7-Zip": "software.install",
        "cherche VLC dans le catalogue winget": "software.search",
        "désinstalle Opera Beta": "software.uninstall",
        "liste les logiciels installés": "software.inventory",
        "liste les mises à jour disponibles": "software.updates_check",
        "mets VLC à jour": "software.upgrade",
        "ouvre Programmes et fonctionnalités": "software.manual_panel",
    }
    for text, expected in cases.items():
        assert coverage.classify(text)[0] == expected, text
    excluded = {
        "comment installer OpenSSH sur Windows": "how_to_or_command_question",
        "crée un script bash pour installer GCC": "script_or_document_generation",
        "j'ai installé ChatGPT mais je ne le retrouve pas, cherche l'application": "software_search_for_an_already_installed_application",
        "je confirme que Opera GX est bien installé": "success_confirmation",
        "[Reprise automatique de tâche longue] mets à jour l'étape": "automatic_long_task_resume",
    }
    for text, reason in excluded.items():
        assert coverage.classify(text)[1] == reason, text
    assert coverage.classify("Installe VLC", conversation_title="Forge benchmark éphémère")[1] == "benchmark_ephemeral_conversation"
    rows = [
        {"text": "Installe VLC", "title": ""},
        {"text": "installe   VLC!", "title": ""},
        {"text": "Désinstalle VLC", "title": ""},
        {"text": "comment installer VLC", "title": ""},
    ]
    result = coverage.analyze(rows, POLICY)
    assert result["coverage"]["counts_by_family"]["software.install"] == 1
    assert result["coverage"]["counts_by_family"]["software.uninstall"] == 1
    assert "software.install" in result["coverage"]["eligible_r4_families"]
    assert result["source"]["tool_names_read"] is False
    assert result["source"]["tool_results_read"] is False
    assert result["privacy"] == {
        "plaintext_published": False,
        "identifiers_published": False,
        "personal_data_published": False,
    }
    print("Tool Selection v1.6 Coverage OK - direct actions only, deduplicated, aggregate, text-only")


if __name__ == "__main__":
    main()
