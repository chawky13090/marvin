"""Régression : réparation des paramètres array/object sérialisés en chaîne (v2.526).

Incident réel reproduit (conversation « PowerPoint article Windows RDP », backend
2.529.0) : le modèle a appelé `pptx_create` avec `slides` comme CHAÎNE contenant du
JSON (`"[{...}]"`) au lieu d'un tableau. Rejeté par `validate_tool_args`, IDENTIQUE
9 fois d'affilée sur 9 tours de conversation, sans jamais s'adapter au message
d'erreur — l'utilisateur n'a jamais obtenu ses images dans le PowerPoint.

`prepare_tool_call_for(TOOLS_SPEC)` répare désormais ce cas AVANT validation, pour
tout outil et tout champ déclaré `array`/`object` par son schéma — pas seulement
`pptx_create`. Ces tests rejouent l'incident exact, puis vérifient que les vraies
erreurs (JSON invalide, mauvais type décodé) restent des erreurs claires.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_safety
import agent_tool_step as step
from tools import TOOLS_SPEC


def _check_real_incident_replayed() -> None:
    """Rejoue l'argument EXACT reçu 9 fois par le backend réel."""
    prepare = step.prepare_tool_call_for(TOOLS_SPEC)
    slides_payload = [
        {
            "bullets": [
                "Bureau à distance Windows (RDP)",
                "Changements majeurs de sécurité",
                "Date effective : Avril 2026",
            ],
            "image_caption": "Raccourcis Bureau à distance",
        }
    ]
    raw_args = {
        "output_path": "C:\\Users\\Chawb\\secretary-ai\\data\\RDP_Windows_Avril_2026.pptx",
        "slides": json.dumps(slides_payload, ensure_ascii=False),
    }
    prepared = prepare("pptx_create", raw_args)
    assert isinstance(prepared.arguments["slides"], list), (
        f"toujours une chaîne : {type(prepared.arguments['slides'])}"
    )
    assert prepared.arguments["slides"] == slides_payload

    validate = agent_safety.validator_for(TOOLS_SPEC)
    assert validate("pptx_create", prepared.arguments) is None, (
        "la validation doit réussir une fois le tableau réparé"
    )


def _check_invalid_json_stays_a_clear_error() -> None:
    """Une chaîne qui n'est pas du JSON du tout : erreur inchangée, pas de crash."""
    prepare = step.prepare_tool_call_for(TOOLS_SPEC)
    validate = agent_safety.validator_for(TOOLS_SPEC)
    prepared = prepare("pptx_create", {"output_path": "x.pptx", "slides": "pas du json"})
    assert prepared.arguments["slides"] == "pas du json"
    error = validate("pptx_create", prepared.arguments)
    assert error is not None and "array" in error


def _check_wrong_decoded_type_stays_a_clear_error() -> None:
    """JSON valide, mais qui décode vers un type différent de celui attendu."""
    prepare = step.prepare_tool_call_for(TOOLS_SPEC)
    validate = agent_safety.validator_for(TOOLS_SPEC)
    prepared = prepare(
        "pptx_create", {"output_path": "x.pptx", "slides": '"une chaîne JSON valide"'}
    )
    assert prepared.arguments["slides"] == '"une chaîne JSON valide"'
    error = validate("pptx_create", prepared.arguments)
    assert error is not None and "array" in error


def _check_unknown_tool_never_crashes() -> None:
    """Un outil absent du registre : aucune réparation tentée, jamais d'exception."""
    prepare = step.prepare_tool_call_for(TOOLS_SPEC)
    prepared = prepare("outil_totalement_inconnu", {"x": "[1, 2, 3]"})
    assert prepared.arguments["x"] == "[1, 2, 3]"


def _check_backward_compatible_without_schemas() -> None:
    """`prepare_tool_call` nu (sans schemas_by_name) reste utilisable tel quel —
    c'est le cas de tous les appels historiques (tests, autres modules)."""
    prepared = step.prepare_tool_call("pptx_create", {"slides": '[{"title": "x"}]'})
    assert prepared.arguments["slides"] == '[{"title": "x"}]', (
        "sans schéma lié, aucune réparation ne doit être tentée"
    )


def main() -> int:
    _check_real_incident_replayed()
    _check_invalid_json_stays_a_clear_error()
    _check_wrong_decoded_type_stays_a_clear_error()
    _check_unknown_tool_never_crashes()
    _check_backward_compatible_without_schemas()
    print(
        "Stringified Array Repair OK - incident reel rejoue et corrige, "
        "vraies erreurs preservees, retrocompatibilite intacte."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
