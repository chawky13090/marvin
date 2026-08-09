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


def requested_exact_tool_mentions_from_text(
    text: str,
    *,
    tool_names: Collection[str],
) -> set[str]:
    """Isole les noms exacts que l'utilisateur demande explicitement d'executer."""
    mentioned = exact_tool_mentions_from_text(text, tool_names=tool_names)
    if not mentioned:
        return set()
    normalized = str(text).lower()
    verb = r"(?:utilis(?:e|er|ez)|ex[ée]cut(?:e|er|ez)|appell(?:e|er|ez)|lanc(?:e|er|ez)|emploie|invoqu(?:e|er|ez))"
    requested: set[str] = set()
    for name in mentioned:
        aliases = {str(name).lower(), str(name).lower().replace("_", " ")}
        for alias in aliases:
            escaped = re.escape(alias)
            negative = re.search(
                rf"(?:\bne\s+|\bn['’]\s*|\bsans\s+)(?:pas\s+)?{verb}[^.!?\n]{{0,100}}{escaped}",
                normalized,
            )
            positive = re.search(
                rf"(?:\b{verb}\b[^.!?\n]{{0,100}}{escaped}|\b(?:outil|tool)\s+{escaped}\b)",
                normalized,
            )
            if positive and not negative:
                requested.add(name)
                break
    return requested
