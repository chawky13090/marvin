"""Décomposition et synthèse bornées de raisonnements LLM sans outils."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any


Generator = Callable[..., Awaitable[str | dict[str, Any]]]

_generate: Generator | None = None
_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex
_MAX_GOAL_LENGTH = 20_000
_MAX_SUBTASKS = 5
_MAX_SUBTASK_LENGTH = 4_000
_MAX_WORK_RESULT_LENGTH = 12_000
_MAX_SYNTHESIS_INPUT_LENGTH = 50_000


def configure(
    *,
    generate: Generator,
    id_factory: Callable[[], str] | None = None,
) -> None:
    global _generate, _id_factory
    _generate = generate
    _id_factory = id_factory or (lambda: uuid.uuid4().hex)


def _generator() -> Generator:
    if _generate is None:
        raise RuntimeError("Le moteur de raisonnement parallèle n'est pas configuré.")
    return _generate


def _generation_result(
    value: str | dict[str, Any] | None,
) -> tuple[str, str | None]:
    used_model = None
    if isinstance(value, dict):
        raw_model = value.get("model")
        used_model = str(raw_model)[:200] if raw_model else None
        value = value.get("text") or value.get("response") or ""
    return str(value or "").strip(), used_model


def _validate(
    args: dict[str, Any],
) -> tuple[str, list[str], str | None]:
    raw_goal = args.get("goal", args.get("objectif"))
    if not isinstance(raw_goal, str) or not raw_goal.strip():
        raise ValueError("Paramètre 'goal' requis (l'objectif à décomposer).")
    goal = raw_goal.strip()
    if len(goal) > _MAX_GOAL_LENGTH:
        raise ValueError(f"'goal' est limité à {_MAX_GOAL_LENGTH} caractères.")

    raw_subtasks = args.get("subtasks")
    if raw_subtasks is None:
        subtasks: list[str] = []
    elif not isinstance(raw_subtasks, list):
        raise ValueError("'subtasks' doit être une liste de chaînes.")
    else:
        subtasks = []
        for item in raw_subtasks:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Chaque sous-tâche doit être une chaîne non vide.")
            item = item.strip()
            if len(item) > _MAX_SUBTASK_LENGTH:
                raise ValueError(
                    f"Chaque sous-tâche est limitée à {_MAX_SUBTASK_LENGTH} caractères."
                )
            subtasks.append(item)
        if len(subtasks) > _MAX_SUBTASKS:
            raise ValueError(f"'subtasks' est limité à {_MAX_SUBTASKS} éléments.")

    raw_model = args.get("model")
    if raw_model is not None and not isinstance(raw_model, str):
        raise ValueError("'model' doit être une chaîne.")
    model = raw_model.strip() if isinstance(raw_model, str) else None
    if model and len(model) > 200:
        raise ValueError("'model' est limité à 200 caractères.")
    return goal, subtasks, model or None


def _parse_subtasks(raw: str) -> list[str]:
    output: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith(("-", "•", "*")):
            continue
        item = stripped.lstrip("-•* ").strip()
        if item:
            output.append(item[:_MAX_SUBTASK_LENGTH])
        if len(output) >= _MAX_SUBTASKS:
            break
    return output


async def run(args: dict[str, Any]) -> dict[str, Any]:
    """Raisonne en parallèle sans outils puis synthétise avec un contexte borné."""
    try:
        goal, subtasks, model = _validate(args)
        generate = _generator()
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}

    trace_id = _id_factory()
    decomposition_model = None
    if not subtasks:
        prompt = (
            f"Objectif : {goal}\n\n"
            "Décompose cet objectif en 2 à 5 sous-tâches INDÉPENDANTES, chacune "
            "traitable sans le résultat des autres. Réponds uniquement par une liste "
            "à puces, une sous-tâche claire par ligne."
        )
        try:
            raw, decomposition_model = _generation_result(
                await generate(
                    prompt,
                    model=model,
                    timeout=90,
                    return_metadata=True,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return {
                "error": f"Décomposition impossible : {str(exc)[:160]}",
                "trace_id": trace_id,
                "phase": "decomposition",
            }
        subtasks = _parse_subtasks(raw)

    if len(subtasks) < 2:
        return {
            "error": (
                "Impossible de produire au moins deux sous-tâches indépendantes; "
                "utilise la boucle d'agent normale pour une tâche unique."
            ),
            "trace_id": trace_id,
            "phase": "decomposition",
        }

    async def work(index: int, subtask: str) -> dict[str, Any]:
        prompt = (
            f"Objectif global : {goal}\n\n"
            f"Sous-tâche {index + 1} (traite uniquement celle-ci, sans outil) : "
            f"{subtask}\n\nRéponds de façon complète et autonome."
        )
        try:
            result, used_model = _generation_result(
                await generate(
                    prompt,
                    model=model,
                    timeout=180,
                    return_metadata=True,
                )
            )
            if not result:
                raise RuntimeError("réponse vide")
            truncated = len(result) > _MAX_WORK_RESULT_LENGTH
            return {
                "index": index,
                "subtask": subtask,
                "status": "ok",
                "result": result[:_MAX_WORK_RESULT_LENGTH],
                "truncated": truncated,
                "model": used_model,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return {
                "index": index,
                "subtask": subtask,
                "status": "error",
                "error": str(exc)[:160],
                "result": "",
                "truncated": False,
                "model": None,
            }

    outcomes = await asyncio.gather(
        *(work(index, subtask) for index, subtask in enumerate(subtasks))
    )
    successful = [outcome for outcome in outcomes if outcome["status"] == "ok"]
    failed = [outcome for outcome in outcomes if outcome["status"] != "ok"]
    if not successful:
        return {
            "error": "Toutes les sous-tâches ont échoué; aucune synthèse fiable possible.",
            "trace_id": trace_id,
            "phase": "parallel_work",
            "subtasks": subtasks,
            "subtask_results": outcomes,
        }

    digest_parts = [
        (
            f"### Sous-tâche {outcome['index'] + 1} : {outcome['subtask']}\n"
            f"{outcome['result']}"
        )
        for outcome in successful
    ]
    digest = "\n\n".join(digest_parts)
    digest_truncated = len(digest) > _MAX_SYNTHESIS_INPUT_LENGTH
    digest = digest[:_MAX_SYNTHESIS_INPUT_LENGTH]
    synth_prompt = (
        f"Objectif global : {goal}\n\n"
        f"Résultats vérifiés de {len(successful)} sous-tâche(s) :\n\n{digest}\n\n"
        "Fusionne-les en un document cohérent répondant à l'objectif global, "
        "structuré, sans répétition et sans inventer les parties absentes."
    )
    try:
        synthesis, synthesis_model = _generation_result(
            await generate(
                synth_prompt,
                model=model,
                timeout=240,
                return_metadata=True,
            )
        )
        if not synthesis:
            raise RuntimeError("synthèse vide")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return {
            "error": f"Synthèse impossible : {str(exc)[:160]}",
            "trace_id": trace_id,
            "phase": "synthesis",
            "partial": True,
            "subtasks": subtasks,
            "subtask_results": outcomes,
        }

    return {
        "success": True,
        "trace_id": trace_id,
        "answer": synthesis,
        "models": {
            "decomposition": decomposition_model,
            "workers": [outcome.get("model") for outcome in outcomes],
            "synthesis": synthesis_model,
        },
        "subtasks": subtasks,
        "subtask_results": outcomes,
        "partial": bool(failed),
        "failed_subtasks": len(failed),
        "policy": {
            "tool_access": False,
            "max_subtasks": _MAX_SUBTASKS,
            "max_work_result_chars": _MAX_WORK_RESULT_LENGTH,
            "max_synthesis_input_chars": _MAX_SYNTHESIS_INPUT_LENGTH,
            "synthesis_input_truncated": digest_truncated,
        },
        "message": (
            f"{len(successful)}/{len(subtasks)} sous-tâche(s) traitée(s), "
            "puis synthèse produite."
        ),
    }
