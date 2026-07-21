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

    web = cortex.compile_contract("Compare ces solutions", {"evidence": "primary", "output": "report"})
    check(web["forced_tools"] == ["web_deep_research"], "Sources primaires explicites")
    check(web["resolved"]["output"] == "report", "Livrable rapport")

    council = cortex.compile_contract("Décide entre A et B", {"review": "council5"})
    check(council["forced_tools"] == ["ai_model_council"], "Council explicite obligatoire")
    swarm = cortex.compile_contract("Étudie le marché", {"review": "swarm"})
    check(swarm["forced_tools"] == ["ai_research_swarm"], "Research Swarm explicite obligatoire")
    team = cortex.compile_contract("Compare plusieurs architectures", {"review": "team"})
    check(team["forced_tools"] == ["ai_adaptive_team"], "Équipe adaptative explicite obligatoire")

    invalid = cortex.normalize_contract({"privacy": "pirate", "unknown": "x"})
    check(invalid["privacy"] == "auto" and "unknown" not in invalid, "Entrée client filtrée")

    private = cortex.compile_contract("Analyse ce mot de passe et mon email")
    check(private["resolved"]["privacy"] == "hybrid_redacted", "Sensibilité détectée")
    check(private["forced_tools"] == [], "Sensibilité ne déclenche pas d'action")

    print("Cortex OK - contrat, explicabilité et garde-fous déterministes.")


if __name__ == "__main__":
    main()
