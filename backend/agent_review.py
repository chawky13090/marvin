"""Revue independante des reponses et actions du moteur agentique Marvin.

Le runner decide quand demander une revue; ce module execute le controle sans connaitre
la boucle, la persistance ou le protocole SSE. Une panne du relecteur ne masque jamais la
reponse principale et ne vaut jamais validation positive.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

import cloud_routing
import tools


Generate = Callable[..., Awaitable[str | None]]


RESPONSE_REVIEW_PROMPT = (
    "Tu es un RELECTEUR technique indépendant. Un AUTRE modèle vient de répondre à un "
    "technicien informatique. Cherche UNIQUEMENT des problèmes GRAVES parmi ces 4 "
    "catégories précises — RIEN d'autre :\n"
    "1. Un identifiant/nom de modèle/ID technique INVENTÉ, présenté comme réel sans "
    "avoir été vérifié.\n"
    "2. Une information factuellement FAUSSE ou probablement périmée, présentée comme certaine.\n"
    "3. Une dégradation de sécurité RÉELLE déguisée en amélioration (mot de passe vidé, "
    "authentification supprimée sans remplacement, permissions 777, pare-feu désactivé).\n"
    "4. Une syntaxe shell NON évaluée (ex. littéralement `$(date ...)`) écrite telle quelle "
    "dans un contenu censé être lu tel quel (document/rapport), pas dans un script exécutable.\n\n"
    "IMPORTANT — N'ES PAS un relecteur de style : IGNORE tout ce qui est préférence, "
    "convention, formulation, usage de `sudo`, absence d'étape « vérification finale », "
    "ou tout point que le rédacteur original a déjà lui-même signalé comme risque dans sa "
    "réponse. En cas de doute, ne signale RIEN plutôt que de trouver un problème mineur "
    "pour justifier ta relecture — la plupart des réponses sont correctes et méritent « OK ».\n\n"
    "DEMANDE ORIGINALE :\n{query}\n\n"
    "RÉPONSE À VÉRIFIER :\n{response}\n\n"
    "Réponds UNIQUEMENT par « OK » si aucun problème GRAVE des 4 catégories ci-dessus n'est "
    "trouvé, sinon par une liste à puces courte (3 points maximum) — rien d'autre."
)


def pick_critic_model(active_model: str | None) -> str | None:
    """Choisit un modèle configuré différent, sans inventer de fournisseur."""
    if not active_model or not cloud_routing.is_cloud_model(active_model):
        return None
    _, overrides = cloud_routing.get_cloud_config()
    return next((model for model in overrides.values() if model and model != active_model), None)


async def review_response(
    user_query: str,
    full_content: str,
    active_model: str,
    *,
    force: bool = False,
    generate: Generate | None = None,
) -> str | None:
    """Retourne uniquement les problèmes substantiels du relecteur indépendant."""
    if not force and "```" not in full_content:
        return None
    generator = tools._ollama_generate if generate is None else generate
    try:
        prompt = RESPONSE_REVIEW_PROMPT.format(
            query=(user_query or "")[:2000], response=full_content[:6000]
        )
        verdict = await generator(
            prompt,
            model=pick_critic_model(active_model),
            timeout=90,
        )
        verdict = (verdict or "").strip()
        if not verdict or verdict.upper().startswith("OK"):
            return None
        if len(re.sub(r"[\s\-•*]", "", verdict)) < 15:
            return None
        return verdict
    except Exception:
        return None


async def review_action(
    user_query: str,
    tool_name: str,
    arguments: dict,
    model: str | None = None,
    *,
    generate: Generate | None = None,
) -> str | None:
    """Vérifie que le type et la cible d'une action sensible suivent la demande."""
    generator = tools._ollama_generate if generate is None else generate
    try:
        prompt = (
            "Tu es un contrôleur de sécurité. Tu dois détecter si une action ne correspond PAS "
            "à la demande.\n\n"
            f"DEMANDE : « {user_query} »\n"
            f"ACTION PRÉVUE : {tool_name} avec "
            f"{json.dumps(arguments, ensure_ascii=False)[:400]}\n\n"
            "Le TYPE d'action et ses cibles correspondent-ils à la demande ?\n"
            "- Si l'action fait clairement autre chose que demandé (ex: la demande parle de "
            "supprimer une tâche mais l'action envoie un email), réponds : "
            "PROBLEME: <quoi> en UNE phrase.\n"
            "- Si l'action correspond bien à la demande, réponds uniquement : OK\n"
            "Réponse :"
        )
        verdict = (await generator(prompt, model=model, timeout=60) or "").strip()
        if not verdict or verdict.upper().startswith("OK") or len(verdict) < 5:
            return None
        verdict = verdict.split("\n")[0]
        verdict = re.sub(
            r"^\s*PROBL[EÈ]?ME\s*:\s*", "", verdict, flags=re.IGNORECASE
        )
        return verdict[:200] if len(verdict) >= 5 else None
    except Exception:
        return None
