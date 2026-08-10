"""Oracle Forge v1.2 independant du registre produit et sans execution."""

from __future__ import annotations

from typing import Any


def evaluate_candidate_names(
    item: dict[str, Any], candidate_names: list[str]
) -> dict[str, Any]:
    acceptable = {str(name) for name in item.get("acceptable_tools", [])}
    forbidden = {str(name) for name in item.get("forbidden_tools", [])}
    proposed = [str(name) for name in candidate_names]
    accepted = bool(acceptable & set(proposed)) if acceptable else not proposed
    return {
        "accepted": accepted and not bool(forbidden & set(proposed)),
        "acceptable_match": sorted(acceptable & set(proposed)),
        "forbidden_match": sorted(forbidden & set(proposed)),
        "candidate_count": len(proposed),
    }
