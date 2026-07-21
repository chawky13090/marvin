"""Régressions déterministes des intentions conversationnelles de Marvin."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from intent_guard import (  # noqa: E402
    is_quiz_answer,
    skill_match_text,
    tool_suppression_reason,
    wants_direct_text,
    wants_command_text_only,
    wants_model_council,
    wants_no_tools,
    workspace_followup,
)
from skills import _keywords  # noqa: E402


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def main() -> int:
    check(
        wants_no_tools("Attention, je réponds à la question donc je ne déclenche pas d'outils."),
        "négation explicite avec ne",
    )
    check(
        wants_no_tools("je repond a la question donc je declache pas d outils de sauvegarde"),
        "négation explicite saisie rapidement",
    )
    check(not wants_no_tools("utilise l'outil quiz"), "demande explicite d'outil")
    check(wants_no_tools("Je ne veux pas que tu utilises d'outil."), "refus formulé avec vouloir")
    check(wants_no_tools("Pas besoin d'outil, explique simplement."), "outil déclaré inutile")
    check(
        wants_command_text_only("Donne-moi la commande PowerShell, ne lance rien"),
        "commande demandee comme texte avec negation",
    )
    check(
        not wants_command_text_only("Donne-moi la commande puis execute-la"),
        "execution explicitement demandee",
    )

    quiz_messages = [
        {"role": "assistant", "content": "Question n°2 — Quels sont les types de sauvegarde ?"},
        {"role": "user", "content": "backup total et incremental"},
    ]
    check(is_quiz_answer(quiz_messages, "backup total et incremental"), "réponse de quiz")
    check(
        tool_suppression_reason(quiz_messages, "backup total et incremental") == "quiz_answer",
        "suppression des outils pendant le quiz",
    )

    check(
        wants_direct_text("Crée un questionnaire de 10 questions pour mon TSSR"),
        "questionnaire directement dans le chat",
    )
    check(not wants_direct_text("Utilise l'outil quiz pour mon TSSR"), "quiz interactif demandé")
    check(not wants_direct_text("Crée un questionnaire TSSR en PDF"), "artefact PDF demandé")

    history = [
        {"role": "user", "content": "diagnostique mon imprimante"},
        {"role": "assistant", "content": "Je peux lancer le diagnostic."},
        {"role": "user", "content": "vas-y"},
    ]
    check(
        skill_match_text(history, "vas-y") == "diagnostique mon imprimante vas-y",
        "follow-up anaphorique enrichi",
    )
    check(
        skill_match_text(quiz_messages, "backup total et incremental") == "backup total et incremental",
        "réponse courte autonome non enrichie",
    )
    check("quelles" not in _keywords("Quelles sont les conditions de certification PASSI ?"),
          "mot interrogatif exclu de l'ancrage des compétences")

    check(wants_model_council("cherche en mode council"), "déclenchement Council explicite")
    check(wants_model_council("demande à 5 modèles différents de juger"), "Council à cinq modèles")
    check(not wants_model_council("donne-moi ton avis"), "avis simple sans Council")

    mission_id = "30e06720235047178855b6736d4f94dc"
    workspace_history = [
        {"role": "assistant", "content": f"Mission Code Workspace `{mission_id}` bloquee."},
        {"role": "user", "content": "regarde le dernier livrable de Code Forge et re-ecris le script"},
    ]
    route = workspace_followup(workspace_history, workspace_history[-1]["content"])
    check(route == {"tool": "code_workspace_control", "mission_id": mission_id, "action": "resume"},
          "reprise du dernier snapshot Code Workspace")
    status_route = workspace_followup(
        workspace_history + [{"role": "user", "content": "ou en est la progression ?"}],
        "ou en est la progression ?",
    )
    check(status_route and status_route["tool"] == "code_workspace_status",
          "statut de la mission existante")
    print("Garde-fous d'intention OK - 21 régressions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
