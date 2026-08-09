"""Politiques déterministes appliquées entre deux itérations du Runner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


_NATIVE_TOOL_CALL_LIMITS = {
    # Outils de découverte, jamais des moteurs de travail longs.
    "tool_search": 4,
    "web_search": 3,
    "web_browse": 12,
    "web_browser_open": 12,
    "web_site_crawl": 4,
    # Une mission visuelle nécessite plusieurs perceptions et actions différentes.
    # Ce plafond empêche une boucle infinie sans dicter la stratégie au modèle.
    "computer_control": 24,
}
_NATIVE_DEFAULT_TOOL_CALL_LIMIT = 8

_UNEXECUTED_ACTION_RE = re.compile(
    r"\b(?:je\s+(?:vais|peux|dois)\s+|je\s+)"
    r"(?:lance(?:r)?|effectue(?:r)?|ex[ée]cute(?:r)?|d[ée]marre(?:r)?|"
    r"consulte(?:r)?|recherche(?:r)?|visite(?:r)?)\b",
    re.IGNORECASE,
)
_TOOL_ACTION_RE = re.compile(
    r"\b(?:recherches?|web|internet|site|page|outil|analyse|scan|test|"
    r"commande|script|fichier|document|mission)\b",
    re.IGNORECASE,
)
_COMPUTER_ACTION_INTENT_RE = re.compile(
    r"\b(?:navigu(?:e|er)|ouvre|ouvrir|clique|cliquer|remplis|remplir|"
    r"r[ée]serve|r[ée]server|pilote|piloter|contr[ôo]le|contr[ôo]ler)\b",
    re.IGNORECASE,
)
_COMPUTER_TARGET_RE = re.compile(
    r"\b(?:site|page|web|navigateur|chrome|edge|fen[êe]tre|formulaire|restaurant)\b"
    r"|https?://",
    re.IGNORECASE,
)
_CONTINUATION_REQUEST_RE = re.compile(
    r"\b(?:continue|continuer|reprends?|reprendre|r[ée]essaie|r[ée]essayer|"
    r"re[\s-]?teste|retenter?|corrige|corriger|trouve\s+une\s+solution|"
    r"tu\s+dois\s+le\s+faire|fais[\s-]?le|vas[\s-]?y)\b",
    re.IGNORECASE,
)

_DIRECT_FILE_LIST_RE = re.compile(
    r"\b(?:liste|lister|affiche|afficher|montre|montrer|combien|contenu)\b"
    r".*\b(?:fichiers?|dossiers?|r[ée]pertoire|r[ée]pertoires|[ée]l[ée]ments?)\b"
    r"|\b(?:fichiers?|dossiers?|r[ée]pertoire|r[ée]pertoires|[ée]l[ée]ments?)\b"
    r".*\b(?:liste|lister|affiche|afficher|montre|montrer|combien|contenu)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModelSwitch:
    model: str
    event: dict[str, Any]


def render_terminal_file_list(
    user_query: str,
    successful_results: list[dict[str, Any]],
) -> str | None:
    """Rend les listes simples depuis le reçu exact, sans seconde inférence LLM.

    Le modèle reste libre de choisir l'outil. Une fois une lecture déterministe
    réussie, recompter ou recopier les entrées avec un petit modèle local ajoute
    de la latence et peut créer un faux succès. Les requêtes d'analyse plus
    complexes conservent le parcours LLM normal.
    """
    if not _DIRECT_FILE_LIST_RE.search(str(user_query or "")):
        return None
    latest = next(
        (
            item
            for item in reversed(successful_results or [])
            if item.get("tool") == "file_list" and isinstance(item.get("entries"), list)
        ),
        None,
    )
    if not latest:
        return None
    entries = latest["entries"]
    directory_count = sum(
        1 for entry in entries if str(entry.get("type") or "").casefold() == "dossier"
    )
    file_count = len(entries) - directory_count
    observed_count = int(latest.get("count") or len(entries))
    total_count = int(latest.get("total_count") or observed_count)
    current_dir = str(latest.get("current_dir") or "dossier demandé")
    has_more = bool(latest.get("has_more"))
    omitted = int(latest.get("entries_omitted") or 0)

    if has_more:
        summary = (
            f"`{current_dir}` contient **{total_count} éléments**. "
            f"Cette page en affiche **{observed_count}** : "
            f"**{directory_count} dossiers** et **{file_count} fichiers**."
        )
    else:
        summary = (
            f"`{current_dir}` contient **{total_count} éléments** : "
            f"**{directory_count} dossiers** et **{file_count} fichiers**."
        )
    lines = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        kind = str(entry.get("type") or "").casefold()
        size = str(entry.get("size") or "").strip()
        suffix = "/" if kind == "dossier" else (f" — {size}" if size else "")
        lines.append(f"- `{name}{suffix}`")
    if omitted:
        lines.append(f"- … {omitted} entrées supplémentaires restent visibles dans le reçu complet.")
    if has_more:
        lines.append(
            f"- Page suivante disponible à partir de l’offset `{latest.get('next_offset')}`."
        )
    return summary + ("\n\n" + "\n".join(lines) if lines else "")


def retryable_cloud_model_error(exc: Exception) -> bool:
    """Autorise un repli Cloud borné pour une panne de modèle sans contenu partiel."""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return (
            status_code in {402, 404, 408, 409, 425, 429}
            or 500 <= status_code <= 599
        )
    return type(exc).__name__ in {
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
    }


def connectivity_local_fallback(
    *,
    active_model: str,
    profile_name: str,
    local_fallback_model: str,
    privacy_preset: str,
    local_continuity_allowed: bool,
    is_cloud_model: Callable[[str], bool],
    already_attempted: bool,
) -> ModelSwitch | None:
    """Repli local de CONTINUITÉ quand tout le Cloud est devenu inaccessible.

    v2.524 — Distinct du repli de confidentialité (`sensitive_tool_model_switch`) :
    celui-ci se déclenche sur le CONTENU (donnée sensible), pas sur une panne.
    Avant cette fonction, un essaim de modèles Cloud tous injoignables (panne
    réseau, incident fournisseur) épuisait ses tentatives puis renvoyait une
    erreur brute — aucun repli automatique n'existait pour la continuité. Depuis
    v2.593, le contrat central autorise aussi Ultra à poursuivre localement, mais
    uniquement avec un événement dégradé explicite et sans changer le profil.
    """
    if not local_continuity_allowed or already_attempted:
        return None
    if not is_cloud_model(active_model):
        return None
    if not local_fallback_model or is_cloud_model(local_fallback_model):
        return None
    if local_fallback_model == active_model:
        return None
    return ModelSwitch(
        model=local_fallback_model,
        event={
            "type": "model_info",
            "profile": profile_name,
            "model": local_fallback_model,
            "label": f"🔌 Repli local · {local_fallback_model}",
            "provider": "ollama_local",
            "privacyPreset": privacy_preset,
            "privacyMode": f"{privacy_preset}_local_continuity",
            "cloudPreferred": privacy_preset in {"cloud_max", "ultra"},
            "cloudOnly": False,
            "degraded": True,
            "continuityState": "local_continuity",
            "switchReason": "cloud_connectivity_unavailable",
            "switchMessage": (
                "Connexion au Cloud indisponible après plusieurs tentatives : "
                "poursuite avec le modèle local pour ne pas interrompre la conversation."
            ),
        },
    )


def sensitive_tool_model_switch(
    *,
    tool_calls: list[dict[str, Any]],
    active_model: str,
    profile_name: str,
    local_fallback_model: str,
    ultra_cloud_only: bool,
    is_cloud_model: Callable[[str], bool],
    is_sensitive_tool: Callable[[str], bool],
) -> ModelSwitch | None:
    """Impose un repli local avant de réinjecter une donnée sensible."""
    if ultra_cloud_only or not tool_calls or not is_cloud_model(active_model):
        return None
    if not any(
        is_sensitive_tool(call.get("function", {}).get("name", ""))
        for call in tool_calls
    ):
        return None
    return ModelSwitch(
        model=local_fallback_model,
        event={
            "type": "model_info",
            "profile": profile_name,
            "model": local_fallback_model,
            "label": "🔒 Repli local (donnée sensible détectée)",
        },
    )


def build_skill_nudge(
    *,
    skill: dict[str, Any] | None,
    tools_payload: list[dict[str, Any]],
    full_content: str,
) -> list[dict[str, str]]:
    """Construit la relance unique qui force une compétence à agir."""
    available = {
        spec.get("function", {}).get("name")
        for spec in tools_payload
        if spec.get("function", {}).get("name")
    }
    requested = [
        name for name in (skill or {}).get("tools", [])
        if name in available
    ]
    messages: list[dict[str, str]] = []
    if full_content.strip():
        messages.append({"role": "assistant", "content": full_content})
    suffix = (
        f"Utilise EXACTEMENT l'un de ces noms d'outils : {', '.join(requested)}."
        if requested
        else "Utilise l'un des outils fournis."
    )
    messages.append({
        "role": "user",
        "content": (
            "⛔ STOP. Tu as DÉCRIT les étapes au lieu d'AGIR. N'explique plus, "
            "ne réécris pas le plan. Exécute MAINTENANT, via un VRAI appel "
            "d'outil (pas de texte, pas de bloc JSON), l'outil le plus pertinent "
            f"pour la 1ʳᵉ étape — un seul. {suffix}"
        ),
    })
    return messages


def skill_requires_nudge(
    *,
    skill: dict[str, Any] | None,
    tools_payload: list[dict[str, Any]],
    executed_tool_names: set[str],
) -> bool:
    """Relance une compétence uniquement si aucun de ses outils n'a encore agi."""
    available = {
        spec.get("function", {}).get("name")
        for spec in tools_payload
        if spec.get("function", {}).get("name")
    }
    requested = {
        name for name in (skill or {}).get("tools", [])
        if name in available
    }
    return bool(requested) and not bool(requested & executed_tool_names)


def build_empty_response_nudge(*, required_tool_names: set[str]) -> dict[str, str]:
    """Construit l'unique relance autorisée après une sortie modèle vide."""
    required = ", ".join(sorted(required_tool_names))
    requirement = (
        f" Il reste au moins un outil obligatoire à exécuter : {required}."
        if required
        else ""
    )
    return {
        "role": "user",
        "content": (
            "Ta réponse précédente ne contient ni texte utile ni appel d'outil."
            f"{requirement} Réponds maintenant à la demande initiale : émets un appel "
            "d'outil natif si une preuve est requise, sinon livre directement une "
            "réponse utile. Ne décris pas une action future et ne reste pas silencieux."
        ),
    }


def native_tool_call_limit(tool_name: str) -> int:
    """Budget par capacité pour éviter une boucle sans retirer la décision au LLM."""
    return _NATIVE_TOOL_CALL_LIMITS.get(
        str(tool_name or ""),
        _NATIVE_DEFAULT_TOOL_CALL_LIMIT,
    )


def build_native_budget_nudge(tool_names: set[str]) -> dict[str, str]:
    names = ", ".join(sorted(tool_names))
    return {
        "role": "user",
        "content": (
            "Le budget de répétition de cette capacité est atteint pour ce tour : "
            f"{names}. N'appelle plus ces capacités. Analyse les résultats déjà observés, "
            "recherche une capacité complémentaire avec les schémas encore visibles, "
            "ou conclus honnêtement avec le blocage et les preuves disponibles."
        ),
    }


def promises_unexecuted_action(
    content: str,
    *,
    executed_tool_names: set[str],
    tools_available: bool,
) -> bool:
    """Détecte une promesse d'action présentée à tort comme résultat terminal."""
    text = str(content or "")
    return (
        tools_available
        and bool(_UNEXECUTED_ACTION_RE.search(text))
        and bool(_TOOL_ACTION_RE.search(text))
    )


def requires_computer_action_nudge(
    user_query: str,
    *,
    executed_tool_names: set[str],
    available_tool_names: set[str],
    successful_calls: list[dict[str, str]] | None = None,
    recent_user_queries: list[str] | None = None,
) -> bool:
    """Détecte une mission PC/Web terminée sans action mutatrice réussie."""
    text = str(user_query or "")
    if _CONTINUATION_REQUEST_RE.search(text):
        prior_context = "\n".join(
            str(item or "")
            for item in (recent_user_queries or [])[-4:]
            if str(item or "").strip() and str(item or "").strip() != text.strip()
        )
        if prior_context:
            text = f"{prior_context}\n{text}"
    successful_computer_action = any(
        call.get("tool") == "computer_control"
        and '"action": "observe"' not in str(call.get("args") or "")
        for call in (successful_calls or [])
    )
    return (
        "computer_control" in available_tool_names
        and not successful_computer_action
        and bool(_COMPUTER_ACTION_INTENT_RE.search(text))
        and bool(_COMPUTER_TARGET_RE.search(text))
    )


def build_computer_action_nudge() -> list[dict[str, str]]:
    return [{
        "role": "user",
        "content": (
            "La dernière demande `user` exige une action PC/Web concrète, mais aucune "
            "action mutatrice n'a encore réussi. Une simple observation, une ancienne "
            "réponse assistant ou la fenêtre de bureau "
            "courante ne peut pas annuler cette demande. Appelle maintenant "
            "`computer_control`. Si une URL est connue, commence par "
            "`action=navigate` avec `surface=browser`, puis observe et poursuis. "
            "Une ancienne demande de confirmation n'est pas l'autorisation courante : "
            "la passerelle appliquera elle-même le mode actuel (Normal, Auto ou Accès "
            "complet). Ne prétends pas être bloqué avant d'avoir réellement retenté. "
            "Ne demande pas à l'utilisateur de faire une étape que l'outil peut réaliser."
        ),
    }]


def build_action_execution_nudge(*, available_tool_names: set[str]) -> list[dict[str, str]]:
    """Relance une seule fois le modèle lorsqu'il promet d'agir sans reçu d'outil."""
    names = ", ".join(sorted(available_tool_names)[:20])
    suffix = f" Outils disponibles pertinents : {names}." if names else ""
    return [{
        "role": "user",
        "content": (
            "Tu viens d'annoncer une action future sans l'avoir exécutée. "
            "Une promesse n'est pas un résultat. Émets maintenant un véritable appel "
            "d'outil natif, ou explique immédiatement le blocage concret sans prétendre "
            f"que l'action est lancée.{suffix}"
        ),
    }]


def should_suppress_model_text(
    *,
    has_blocking_outcomes: bool,
    required_tool_names: set[str],
    executed_tool_names: set[str],
) -> bool:
    """Masque un brouillon tant qu'une preuve ou un gate obligatoire manque."""
    return has_blocking_outcomes or bool(
        required_tool_names - executed_tool_names
    )


def render_blocking_outcomes(outcomes: dict[str, dict[str, Any]]) -> str | None:
    """Produit un refus explicite lorsqu'un reçu Forge reste négatif."""
    if not outcomes:
        return None
    details: list[str] = []
    for failed_tool, receipt in outcomes.items():
        report = receipt.get("test_report")
        failed_steps = receipt.get("failed_steps") or (
            report.get("failed_steps") if isinstance(report, dict) else []
        ) or []
        reason = (
            receipt.get("error")
            or receipt.get("message")
            or "gate de qualité non validé"
        )
        suffix = (
            f" Étapes en échec : {', '.join(map(str, failed_steps))}."
            if failed_steps
            else ""
        )
        details.append(f"- `{failed_tool}` : {reason}.{suffix}")
    return (
        "## Validation non obtenue\n\n"
        "Je ne peux pas annoncer que le code ou les tests ont réussi : "
        "le dernier reçu Forge est négatif.\n\n"
        + "\n".join(details)
        + "\n\nLe livrable reste refusé tant qu'une correction suivie d'un "
        "nouveau reçu `production_ready=true` n'a pas été observée."
    )


def render_latest_web_result(
    successful_results: list[dict[str, Any]],
) -> str | None:
    """Restitue le dernier reçu Web si le modèle répète une promesse d'action."""
    result = next(
        (
            item
            for item in reversed(successful_results)
            if item.get("tool") in {"web_search", "web_research", "web_deep_research"}
        ),
        None,
    )
    if not result:
        return None
    answer = str(result.get("answer") or result.get("message") or "").strip()
    sources = [
        source
        for source in result.get("sources") or []
        if isinstance(source, dict)
        and str(source.get("url") or "").startswith(("http://", "https://"))
    ][:20]
    source_lines = "\n".join(
        f"- [{str(source.get('title') or source['url']).strip()}]({source['url']})"
        for source in sources
    )
    if not answer and not source_lines:
        return None
    return (
        (answer or "La recherche est terminée.")
        + (f"\n\n### Sources\n\n{source_lines}" if source_lines else "")
    )
