"""Redecouverte bornee d'un outil inconnu, sans execution implicite.

Le nom produit par le modele est traite comme une requete de recherche uniquement.
Les candidats proviennent exclusivement du catalogue reel. Le modele doit ensuite
emettre un nouvel appel natif, qui repasse par le schema, les permissions, la
confirmation, l'idempotence et la verification de resultat ordinaires.
"""

from __future__ import annotations

import re
import os
import unicodedata
from collections.abc import Iterable, Mapping
from difflib import SequenceMatcher
from typing import Any

from capability_catalog import CapabilityCatalog, CapabilityDescriptor


_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,119}$")
_TOKEN = re.compile(r"[a-z0-9]{2,}")
_GENERIC_TOKENS = {
    "action", "active", "application", "existing", "installed", "named",
    "program", "system", "tool", "windows",
}
_CONFLICTING_INTENTS = (
    ({"stop", "kill", "uninstall", "delete", "remove"}, {"list", "inventory", "read", "search"}),
    ({"list", "inventory", "enumerate", "read", "search"}, {"kill", "delete", "remove", "uninstall"}),
    ({"move", "relocate"}, {"copy", "duplicate"}),
    ({"copy", "duplicate"}, {"move", "relocate"}),
    ({"list", "inventory", "enumerate"}, {"exec", "execute", "run"}),
    ({"text", "phrase"}, {"image", "images", "picture", "pictures"}),
)


def rediscovery_enabled() -> bool:
    """Le produit reste ferme tant que le holdout independant v1.2 manque."""
    return os.environ.get("MARVIN_UNKNOWN_TOOL_REDISCOVERY", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(
        _TOKEN.findall("".join(char for char in text if not unicodedata.combining(char)))
    )


def _tokens(value: Any) -> set[str]:
    return {
        token for token in _normalize(value).split()
        if token not in _GENERIC_TOKENS
    }


def _name_similarity(unknown_name: str, candidate_name: str) -> float:
    unknown = _normalize(unknown_name)
    candidate = _normalize(candidate_name)
    unknown_tokens = _tokens(unknown_name)
    candidate_tokens = _tokens(candidate_name)
    overlap = len(unknown_tokens & candidate_tokens)
    coverage = overlap / max(1, len(candidate_tokens))
    sequence = SequenceMatcher(None, unknown.replace(" ", "_"), candidate.replace(" ", "_")).ratio()
    return (2.5 * overlap) + (1.5 * coverage) + sequence


def _query(tool_name: str, argument_keys: Iterable[str]) -> str:
    # Les valeurs sont volontairement exclues : elles peuvent contenir des secrets.
    keys = [str(key)[:80] for key in argument_keys][:30]
    return " ".join([tool_name.replace("_", " ").replace(".", " "), *keys])


def _public_candidate(descriptor: CapabilityDescriptor) -> dict[str, Any]:
    return {
        "name": descriptor.name,
        "summary": descriptor.summary,
        "required_arguments": list(descriptor.required_arguments),
        "risk": "sensitive" if descriptor.name.startswith(("pc_", "win_", "email_")) else "standard",
        "requires_new_native_call": True,
    }


def _conflicts(query_tokens: set[str], descriptor: CapabilityDescriptor) -> bool:
    candidate_tokens = _tokens(" ".join((descriptor.name, descriptor.summary)))
    for requested, opposite in _CONFLICTING_INTENTS:
        if query_tokens & requested and candidate_tokens & opposite:
            return True
    return False


def resolve_unknown_tool(
    tool_name: str,
    tool_args: Mapping[str, Any] | None,
    specifications: Iterable[dict[str, Any]],
    *,
    maximum_candidates: int = 3,
) -> dict[str, Any]:
    """Retourne des suggestions reelles et consultatives, sans appeler d'outil."""
    raw_name = str(tool_name or "").strip()
    base = {
        "error": f"Outil inconnu : {raw_name}",
        "unknown_tool": True,
        "executed": False,
        "rediscovery": {
            "status": "no_match",
            "candidates": [],
            "advisory_only": True,
            "implicit_execution": False,
            "attempts_used": 1,
            "attempts_remaining": 0,
            "new_native_tool_call_required": True,
        },
    }
    if not _SAFE_NAME.fullmatch(raw_name):
        base["rediscovery"]["status"] = "invalid_name"
        base["rediscovery"]["message"] = "Nom refuse : emettez un appel avec un nom exact du catalogue."
        return base

    catalog = CapabilityCatalog(specifications)
    search_query = _query(raw_name, (tool_args or {}).keys())
    searched = catalog.search(search_query, limit=12)
    ranked: list[tuple[float, str]] = []
    query_tokens = _tokens(search_query)
    for position, item in enumerate(searched["candidates"]):
        name = str(item["name"])
        descriptor = catalog.describe(name)
        if descriptor is None or _conflicts(query_tokens, descriptor):
            continue
        score = _name_similarity(raw_name, name)
        query_overlap = len(_tokens(search_query) & _tokens(
            " ".join([name, str(item.get("summary") or "")])
        ))
        score += 1.25 * query_overlap
        # Le catalogue fournit deja un classement semantique determine par les
        # contrats. Le rang est un signal borne, jamais une substitution.
        score += max(0.0, 3.5 - (0.35 * position))
        ranked.append((score, name))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    bounded = max(1, min(int(maximum_candidates), 3))
    names = [name for score, name in ranked if score >= 3.25][:bounded]
    candidates = []
    for name in names:
        descriptor = catalog.describe(name)
        if descriptor is not None:
            candidates.append(_public_candidate(descriptor))
    if candidates:
        base["rediscovery"]["status"] = "suggestions_available"
        base["rediscovery"]["candidates"] = candidates
        base["rediscovery"]["message"] = (
            "Choisissez uniquement un candidat compatible puis emettez un nouvel appel "
            "d'outil natif. Cette reponse n'a execute aucune action."
        )
    else:
        base["rediscovery"]["message"] = (
            "Aucun candidat suffisamment fiable. Reformulez l'intention ou recherchez "
            "le catalogue avant tout nouvel appel."
        )
    return base
