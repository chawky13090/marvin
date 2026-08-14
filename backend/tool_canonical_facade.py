"""Vue canonique bornée des outils présentés au modèle.

Le registre et les schémas originaux restent l'autorité d'exécution. Ce module ne
fait qu'éliminer, pour une intention simple et certaine, les exécuteurs voisins qui
décrivent la même capacité avec des frontières différentes.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable


_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_TEXT_ONLY_RE = re.compile(
    r"^\s*(?:comment|explique|decris|decrire|quelle?\s+(?:commande|outil)|"
    r"donne(?:-|\s+)?(?:moi\s+)?(?:la\s+)?commande|ecris\s+(?:la\s+)?commande)\b"
)
_NON_APPLICATION_OPEN_RE = re.compile(
    r"\b(?:fichier|dossier|document|pdf|docx|xlsx|pptx|url|site|page\s+web|"
    r"navigateur|parametres|panneau|services\.msc|appwiz\.cpl)\b|"
    r"(?:[a-z]:[\\/]|https?://|\\\\)"
)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(character for character in text if not unicodedata.combining(character))


def _public_names(specifications: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("function", {}).get("name") or "")
        for item in specifications
        if str(item.get("function", {}).get("name") or "")
    }


def _mentions_exact_tool(text: str, names: Iterable[str]) -> bool:
    tokens = set(_TOKEN_RE.findall(text))
    return any(name in tokens for name in names if name)


@dataclass(frozen=True, slots=True)
class CanonicalDecision:
    capability_id: str
    public_tool: str
    fixed_arguments: tuple[tuple[str, Any], ...] = ()
    auxiliary_tools: tuple[str, ...] = ("tool_search",)
    reason_codes: tuple[str, ...] = ()

    @property
    def fixed_argument_map(self) -> dict[str, Any]:
        return dict(self.fixed_arguments)


@dataclass(frozen=True, slots=True)
class CanonicalView:
    tools: tuple[dict[str, Any], ...]
    decision: CanonicalDecision | None
    active: bool
    status: str


def classify_canonical_intent(
    query: str,
    *,
    public_tool_names: Iterable[str] = (),
) -> CanonicalDecision | None:
    """Classe uniquement sept actions simples; toute ambiguïté conserve le chemin normal."""
    text = _normalize(query)
    if not text.strip() or _TEXT_ONLY_RE.search(text):
        return None
    if _mentions_exact_tool(text, public_tool_names):
        return None
    if re.search(r"\b(?:puis|ensuite|apres)\b|[;\n]", text):
        action_verbs = re.findall(
            r"\b(?:ouvre|lance|demarre|execute|installe|desinstalle|supprime|retire|"
            r"mets|mettre|actualise|upgrade|cherche|recherche|trouve|liste|affiche|montre|inventorie)\w*\b",
            text,
        )
        if len(action_verbs) > 1:
            return None

    matches: list[CanonicalDecision] = []

    if re.search(r"\b(?:desinstalle|desinstaller|supprime|retire)\b", text) and re.search(
        r"\b(?:logiciel|programme|application|paquet|winget)\b", text
    ):
        matches.append(CanonicalDecision(
            "software.uninstall", "winget_uninstall",
            auxiliary_tools=("winget_list_installed", "tool_search"),
            reason_codes=("software_object", "uninstall_verb"),
        ))
    elif re.search(r"\b(?:mises?\s+a\s+jour|updates?)\s+(?:disponibles?|possibles?)\b", text) or re.search(
        r"\bliste\w*\b.{0,50}\b(?:mises?\s+a\s+jour|updates?)\b", text
    ):
        matches.append(CanonicalDecision(
            "software.list_upgrades", "winget_list_upgrades",
            reason_codes=("upgrade_inventory",),
        ))
    elif re.search(r"\b(?:mets?|mettre|actualise|upgrade)\b.{0,50}\b(?:a\s+jour|logiciel|programme|application|paquet|tout|tous)\b", text):
        matches.append(CanonicalDecision(
            "software.upgrade", "winget_upgrade",
            auxiliary_tools=("winget_list_upgrades", "tool_search"),
            reason_codes=("software_object", "upgrade_verb"),
        ))
    elif re.search(r"\b(?:installe|installer|installation|ajoute)\b", text) and re.search(
        r"\b(?:logiciel|programme|application|paquet|winget|sur\s+(?:le|ce)\s+pc)\b", text
    ):
        matches.append(CanonicalDecision(
            "software.install", "winget_install",
            auxiliary_tools=("winget_search", "tool_search"),
            reason_codes=("software_object", "install_verb"),
        ))
    elif re.search(r"\b(?:liste|affiche|montre|inventorie|quels?)\w*\b", text) and re.search(
        r"\b(?:logiciels?|programmes?|applications?|paquets?)\s+installe(?:e)?s?\b", text
    ):
        matches.append(CanonicalDecision(
            "software.list_installed", "windows_task",
            fixed_arguments=(("action", "software.list"),),
            reason_codes=("installed_inventory",),
        ))
    elif re.search(r"\b(?:cherche|recherche|trouve)\w*\b", text) and re.search(
        r"\b(?:logiciel|programme|application|paquet|winget|installable)\b", text
    ):
        matches.append(CanonicalDecision(
            "software.search", "winget_search",
            reason_codes=("software_object", "search_verb"),
        ))

    application_action = re.search(r"\b(?:ouvre|lance|demarre|execute)\w*\b", text)
    application_object = re.search(
        r"\b(?:application|appli|logiciel|programme)\b|"
        r"\b(?:bloc-notes|notepad|calculatrice|calc|paint|terminal)\b",
        text,
    )
    if (
        application_action
        and application_object
        and not _NON_APPLICATION_OPEN_RE.search(text)
        and not re.search(r"\b(?:installe|desinstalle|mise\s+a\s+jour)\b", text)
    ):
        matches.append(CanonicalDecision(
            "application.launch", "windows_task",
            fixed_arguments=(("action", "application.launch"),),
            reason_codes=("application_object", "launch_verb"),
        ))

    unique = {item.capability_id: item for item in matches}
    if len(unique) != 1:
        return None
    return next(iter(unique.values()))


def _bounded_schema(
    specification: dict[str, Any],
    decision: CanonicalDecision,
) -> dict[str, Any]:
    clone = copy.deepcopy(specification)
    function = clone["function"]
    prefix = (
        f"CONTRAT CANONIQUE {decision.capability_id}. "
        "Cet outil est l'exécuteur direct de l'intention courante; n'appelle pas un outil "
        "de chemin, d'inventaire ou d'interface à sa place. "
    )
    function["description"] = prefix + str(function.get("description") or "")
    fixed = decision.fixed_argument_map
    properties = function.setdefault("parameters", {}).setdefault("properties", {})
    required = function["parameters"].setdefault("required", [])
    for name, value in fixed.items():
        definition = properties.setdefault(name, {})
        definition["enum"] = [value]
        definition["description"] = (
            f"Valeur imposée par le contrat canonique courant : {value}."
        )
        if name not in required:
            required.append(name)
    return clone


def build_canonical_tool_view(
    query: str,
    selected_tools: list[dict[str, Any]],
    *,
    all_tool_names: Iterable[str],
    enabled: bool = False,
) -> CanonicalView:
    """Retourne une copie bornée sans modifier les schémas d'entrée."""
    if not enabled:
        return CanonicalView(tuple(selected_tools), None, False, "disabled_pending_validation")
    decision = classify_canonical_intent(query, public_tool_names=all_tool_names)
    if decision is None:
        return CanonicalView(tuple(selected_tools), None, False, "not_applicable")

    by_name = {
        str(item.get("function", {}).get("name") or ""): item
        for item in selected_tools
    }
    target = by_name.get(decision.public_tool)
    if target is None:
        diagnostic = by_name.get("tool_search")
        tools = (copy.deepcopy(diagnostic),) if diagnostic is not None else ()
        return CanonicalView(tools, decision, True, "canonical_executor_missing")

    result = [_bounded_schema(target, decision)]
    for name in decision.auxiliary_tools:
        if name == decision.public_tool or name not in by_name:
            continue
        result.append(copy.deepcopy(by_name[name]))
    return CanonicalView(tuple(result), decision, True, "active")
