"""Régressions déterministes du contrat Marvin Cortex (aucun appel LLM)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cortex


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def main() -> None:
    clean = cortex.compile_contract("Bonjour, explique-moi simplement ce concept")
    check(clean["forced_tools"] == [], "Auto ne doit forcer aucun outil")
    check(clean["resolved"]["autonomy"] == "advise", "Une explication reste en conseil")
    check(clean["execution_budget"]["max_tool_steps"] == 10, "Budget standard")

    instant = cortex.compile_contract("Réponds vite", {"effort": "instant"})
    deep = cortex.compile_contract("Analyse complète", {"effort": "deep"})
    mission = cortex.compile_contract("Poursuis cette mission", {"autonomy": "mission"})
    check(instant["execution_budget"]["max_tool_steps"] == 3, "Budget instant")
    check(deep["execution_budget"]["max_tool_steps"] == 16, "Budget approfondi")
    check(mission["execution_budget"]["max_tool_steps"] == 24, "Budget mission")
    check(
        instant["execution_budget"]["max_wall_seconds"]
        < deep["execution_budget"]["max_wall_seconds"]
        < mission["execution_budget"]["max_wall_seconds"],
        "Budgets temporels croissants",
    )
    check("plafond n'est jamais un objectif" in cortex.prompt_block(deep), "Arrêt anticipé explicite")

    web = cortex.compile_contract("Compare ces solutions", {"evidence": "primary", "output": "report"})
    check(web["forced_tools"] == ["web_deep_research"], "Sources primaires explicites")
    check(web["resolved"]["output"] == "report", "Livrable rapport")
    check(web["execution_budget"]["evidence_required"] is True, "Preuves requises exposées")

    natural_web = cortex.compile_contract(
        "quel est l ia derrière Siri de Apple cherche sur le web"
    )
    check(
        natural_web["forced_tools"] == ["web_research"],
        "Une demande Web naturelle explicite doit exécuter la recherche",
    )
    natural_primary = cortex.compile_contract(
        "Compare cela avec les sources officielles"
    )
    check(
        natural_primary["forced_tools"] == ["web_research"],
        "Une demande naturelle de sources primaires doit exécuter la recherche",
    )
    natural_primary_deep = cortex.compile_contract(
        "Recherche approfondie avec les sources officielles"
    )
    check(
        natural_primary_deep["forced_tools"] == ["web_deep_research"],
        "Sources officielles et profondeur explicite imposent la recherche profonde",
    )
    local_file = cortex.compile_contract("Cherche ce fichier dans mon dossier")
    check(local_file["forced_tools"] == [], "Une recherche locale ne doit pas ouvrir le Web")
    latest_file = cortex.compile_contract("Quel est le dernier fichier modifié ?")
    check(latest_file["forced_tools"] == [], "Le mot dernier seul ne doit pas ouvrir le Web")

    council = cortex.compile_contract("Décide entre A et B", {"review": "council5"})
    check(council["forced_tools"] == ["ai_model_council"], "Council explicite obligatoire")
    swarm = cortex.compile_contract("Étudie le marché", {"review": "swarm"})
    check(swarm["forced_tools"] == ["ai_research_swarm"], "Research Swarm explicite obligatoire")
    team = cortex.compile_contract("Compare plusieurs architectures", {"review": "team"})
    check(team["forced_tools"] == ["ai_adaptive_team"], "Équipe adaptative explicite obligatoire")

    small_script = cortex.compile_contract(
        "Crée un script Bash pour installer sur Ubuntu le nécessaire pour du C "
        "et mets-le dans un fichier sur mon bureau"
    )
    check(
        small_script["forced_tools"] == ["ai_code_forge"],
        "Un script simple passe directement par Code Forge sans Adaptive Team implicite",
    )

    invalid = cortex.normalize_contract({"privacy": "pirate", "unknown": "x"})
    check(invalid["privacy"] == "auto" and "unknown" not in invalid, "Entrée client filtrée")

    private = cortex.compile_contract("Analyse ce mot de passe et mon email")
    check(private["resolved"]["privacy"] == "hybrid_redacted", "Sensibilité détectée")
    check(private["forced_tools"] == [], "Sensibilité ne déclenche pas d'action")

    print("Cortex OK - contrat, explicabilité et garde-fous déterministes.")


if __name__ == "__main__":
    main()
