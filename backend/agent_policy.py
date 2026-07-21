"""Politiques textuelles pures utilisees par la boucle agentique Marvin."""

from __future__ import annotations

import re
from collections.abc import Collection


def autotitle_from_text(text: str) -> str:
    """Construit le titre provisoire sans appel LLM ni effet de bord."""
    words = str(text or "").strip().split()
    title = " ".join(words[:6]).strip(" ,.;:!?-")
    if len(words) > 6:
        title += "…"
    return title or "Nouvelle conversation"


def exact_tool_mentions_from_text(
    text: str,
    *,
    tool_names: Collection[str],
) -> set[str]:
    """Retourne uniquement les noms d'outils cites comme tokens complets."""
    if not text:
        return set()
    normalized = str(text).lower()
    found: set[str] = set()
    for name in tool_names:
        if not name:
            continue
        canonical = str(name).lower()
        for alias in {canonical, canonical.replace("_", " ")}:
            if re.search(
                rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])",
                normalized,
            ):
                found.add(str(name))
                break
    return found

