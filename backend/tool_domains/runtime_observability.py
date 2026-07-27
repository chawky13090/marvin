"""Outils d'introspection des défauts et de l'apprentissage de Marvin."""

from __future__ import annotations

from typing import Any

_BUG_KINDS = {"tool_exception", "http_exception"}


def _limit(value: Any, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


async def bug_log_list(
    args: dict[str, Any], *, bug_runtime: Any | None = None
) -> dict[str, Any]:
    if bug_runtime is None:
        import bug_log as bug_runtime

    limit = _limit(args.get("limit"), 20, 100)
    raw_kind = args.get("kind")
    kind = str(raw_kind).strip().lower() if raw_kind not in (None, "") else None
    if kind is not None and kind not in _BUG_KINDS:
        return {
            "error": "Type de bug non pris en charge. Valeurs : "
            + ", ".join(sorted(_BUG_KINDS))
        }
    bugs = bug_runtime.recent(limit=limit, kind=kind)
    if not isinstance(bugs, list):
        return {"error": "Le journal des bugs a retourné un format invalide."}
    return {
        "success": True,
        "count": len(bugs),
        "bugs": bugs,
        "note": (
            "Chaque entrée contient un traceback exploitable; examinez-le avant correction."
            if bugs
            else "Aucun bug enregistré sur la période."
        ),
    }


async def skill_learning_log(
    args: dict[str, Any], *, skills_runtime: Any | None = None
) -> dict[str, Any]:
    if skills_runtime is None:
        import skills as skills_runtime

    raw_skill = args.get("skill")
    skill_name = str(raw_skill).strip() if raw_skill not in (None, "") else None
    if skill_name and len(skill_name) > 160:
        return {"error": "Le nom de compétence est limité à 160 caractères."}
    limit = _limit(args.get("limit"), 10, 100)
    summary = skills_runtime.get_learning_log_for_llm(
        skill_name=skill_name, limit=limit
    )
    entries = skills_runtime.get_learning_log(limit=limit, skill_name=skill_name)
    if not isinstance(entries, list):
        return {"error": "Le journal d'apprentissage a retourné un format invalide."}
    return {
        "success": True,
        "summary": str(summary or ""),
        "log": entries,
    }
