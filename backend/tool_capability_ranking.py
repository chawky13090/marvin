"""Classement lexical déterministe des contrats d'outils Marvin.

Ce routeur ne remplace ni les règles métier ni les embeddings. Il garantit un signal
portable lorsque l'index sémantique local est indisponible et ne sélectionne que des noms
issus de ``TOOLS_SPEC``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable


_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_STOP_WORDS = {
    "afin", "avec", "avoir", "cette", "dans", "des", "donne", "faire", "fait",
    "les", "leur", "mais", "mes", "mon", "pour", "que", "quel", "quelle", "sans",
    "sur", "tout", "tous", "une", "utilise", "via", "veux",
}
_TOKEN_ALIASES = {
    # Les noms d'outils sont contractuellement en anglais alors que Marvin reçoit
    # principalement des demandes françaises. Ces équivalences techniques bornées
    # renforcent le nom exact sans imposer une décision métier au LLM.
    "archiver": "archive",
    "creer": "create",
    "deplacer": "move",
    "discussion": "conversation",
    "epingle": "pin",
    "epingler": "pin",
    "lister": "list",
    "projet": "project",
    "rechercher": "search",
    "renommer": "rename",
    "restaurer": "restore",
    "supprimer": "delete",
}


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def _tokens(value: Any) -> set[str]:
    tokens = {
        token
        for token in _TOKEN_RE.findall(_normalize(value))
        if token not in _STOP_WORDS
    }
    tokens.update(_TOKEN_ALIASES[token] for token in tuple(tokens) if token in _TOKEN_ALIASES)
    return tokens


def _parameter_text(schema: Any) -> str:
    if not isinstance(schema, dict):
        return ""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return ""
    parts: list[str] = []
    for name, definition in properties.items():
        parts.append(str(name))
        if isinstance(definition, dict):
            parts.append(str(definition.get("description") or ""))
            enum = definition.get("enum")
            if isinstance(enum, list):
                parts.extend(map(str, enum[:20]))
    return " ".join(parts)


@dataclass(frozen=True, slots=True)
class CapabilityEntry:
    name: str
    normalized_name: str
    name_tokens: frozenset[str]
    description_tokens: frozenset[str]
    parameter_tokens: frozenset[str]


def build_catalog(tools_spec: Iterable[dict[str, Any]]) -> tuple[CapabilityEntry, ...]:
    entries: list[CapabilityEntry] = []
    for specification in tools_spec:
        function = specification.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        entries.append(CapabilityEntry(
            name=name,
            normalized_name=_normalize(name).replace("_", " "),
            name_tokens=frozenset(_tokens(name.replace("_", " "))),
            description_tokens=frozenset(_tokens(function.get("description"))),
            parameter_tokens=frozenset(_tokens(_parameter_text(function.get("parameters")))),
        ))
    return tuple(entries)


def rank_capabilities(
    query: str,
    catalog: Iterable[CapabilityEntry],
    *,
    limit: int = 8,
    min_score: float = 3.0,
) -> list[tuple[str, float]]:
    """Retourne un classement stable ``[(outil, score)]`` limité aux contrats fournis."""
    query_normalized = _normalize(query)
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    ranked: list[tuple[str, float]] = []
    for entry in catalog:
        name_overlap = query_tokens & entry.name_tokens
        description_overlap = query_tokens & entry.description_tokens
        parameter_overlap = query_tokens & entry.parameter_tokens
        score = (
            5.0 * len(name_overlap)
            + 1.5 * len(description_overlap - name_overlap)
            + 2.0 * len(parameter_overlap - name_overlap)
        )
        if entry.normalized_name and entry.normalized_name in query_normalized:
            score += 12.0
        if score >= min_score:
            ranked.append((entry.name, score))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked[:max(0, min(int(limit), 20))]
