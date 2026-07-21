"""Marvin Cortex — contrat de mission, routage explicable et recettes.

Le contrat reste une donnée déclarative. Il ne contient ni code ni appel d'outil et
ne contourne jamais les confirmations/permissions de l'agent.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AXES = {
    "effort": {"auto", "instant", "standard", "deep", "mission"},
    "evidence": {"auto", "none", "memory", "web", "primary", "connected"},
    "review": {"auto", "none", "verify", "council_if_disagreement", "council5", "search", "swarm", "team"},
    "autonomy": {"auto", "advise", "prepare", "execute", "mission"},
    "privacy": {"auto", "local", "hybrid_redacted", "cloud"},
    "output": {"auto", "chat", "brief", "report", "document", "table", "workflow"},
}

DEFAULT_CONTRACT = {axis: "auto" for axis in AXES}
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_RECIPES_PATH = _DATA_DIR / "cortex_recipes.json"
_LOCK = threading.RLock()


def _clean_text(value: Any, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_contract(raw: dict | None) -> dict:
    """Valide sans erreur un contrat client et ignore tout champ inconnu."""
    raw = raw if isinstance(raw, dict) else {}
    result = dict(DEFAULT_CONTRACT)
    for axis, allowed in AXES.items():
        value = str(raw.get(axis, "auto") or "auto").strip().lower()
        result[axis] = value if value in allowed else "auto"
    result["pinned"] = bool(raw.get("pinned", False))
    recipe_id = _clean_text(raw.get("recipe_id"), 80)
    if recipe_id:
        result["recipe_id"] = recipe_id
    return result


def _explicit_axes(contract: dict) -> list[str]:
    return [axis for axis in AXES if contract.get(axis) != "auto"]


def compile_contract(query: str, raw: dict | None = None) -> dict:
    """Compile les choix explicites et infère seulement une prévisualisation sûre.

    Les inférences Auto n'imposent aucune action sortante. Elles servent au prompt,
    à la provenance et aux seuils de vérification.
    """
    requested = normalize_contract(raw)
    text = _clean_text(query, 8000).lower()
    resolved = {axis: requested[axis] for axis in AXES}
    reasons: list[str] = []

    if resolved["effort"] == "auto":
        if re.search(r"\b(exhausti|approfond|étude complète|analyse complète)\w*", text):
            resolved["effort"] = "deep"; reasons.append("profondeur demandée")
        else:
            resolved["effort"] = "standard"
    if resolved["evidence"] == "auto":
        if re.search(r"\b(sources? officielles?|sources? primaires?|documentation officielle)\b", text):
            resolved["evidence"] = "primary"; reasons.append("sources primaires demandées")
        elif re.search(r"\b(cherche|recherche|sur le web|internet|actuel|derni[eè]r)\w*", text):
            resolved["evidence"] = "web"; reasons.append("information actuelle demandée")
        else:
            resolved["evidence"] = "memory"
    if resolved["review"] == "auto":
        if re.search(r"\b(mode\s+council|council\s*5|cinq\s+mod[eè]les|5\s+mod[eè]les)\b", text):
            resolved["review"] = "council5"; reasons.append("Council explicitement demandé")
        elif risk_score(text) >= 3:
            resolved["review"] = "council_if_disagreement"; reasons.append("enjeu élevé détecté")
        else:
            resolved["review"] = "none"
    if resolved["autonomy"] == "auto":
        # Important : Auto n'accorde pas une autorisation d'exécuter.
        resolved["autonomy"] = "prepare" if re.search(r"\b(plan|propose|prépare|rédige)\w*", text) else "advise"
    if resolved["privacy"] == "auto":
        sensitive = re.search(r"\b(mot de passe|token|secret|confidentiel|données personnelles|mail|ssh)\b", text)
        resolved["privacy"] = "hybrid_redacted" if sensitive else "cloud"
        if sensitive:
            reasons.append("contenu potentiellement sensible")
    if resolved["output"] == "auto":
        if re.search(r"\b(rapport|étude|audit)\b", text): resolved["output"] = "report"
        elif re.search(r"\b(tableau|comparatif|matrice)\b", text): resolved["output"] = "table"
        elif re.search(r"\b(document|word|pdf)\b", text): resolved["output"] = "document"
        else: resolved["output"] = "chat"

    forced_tools: list[str] = []
    explicit = set(_explicit_axes(requested))
    if "review" in explicit and resolved["review"] == "council5":
        forced_tools.append("ai_model_council")
    if "review" in explicit and resolved["review"] == "search":
        forced_tools.append("ai_cortex_search")
    if "review" in explicit and resolved["review"] == "swarm":
        forced_tools.append("ai_research_swarm")
    if "review" in explicit and resolved["review"] == "team":
        forced_tools.append("ai_adaptive_team")
    auto_team = False
    auto_code_forge = False
    if "review" not in explicit and resolved["privacy"] == "cloud":
        try:
            import code_forge
            auto_code_forge = code_forge.should_activate(query)
        except Exception:
            auto_code_forge = False
        try:
            import adaptive_team
            auto_team = adaptive_team.should_auto_activate(query)
        except Exception:
            auto_team = False
        if auto_code_forge:
            resolved["review"] = "team"
            try:
                import adaptive_team
                code_plan = adaptive_team.plan(query)
            except Exception:
                code_plan = {"pipeline": ["code_forge"]}
            if code_plan.get("pipeline", [])[:1] == ["research_swarm"]:
                forced_tools.append("ai_adaptive_team")
                reasons.append("versions et pratiques recherchées avant le contrôle expert du code")
            else:
                forced_tools.append("ai_code_forge")
                reasons.append("livrable code complet soumis au contrôle expert")
        elif auto_team:
            resolved["review"] = "team"
            forced_tools.append("ai_adaptive_team")
            reasons.append("profondeur multi-experts explicitement demandée")
    if "evidence" in explicit:
        if resolved["evidence"] == "web": forced_tools.append("web_research")
        elif resolved["evidence"] == "primary": forced_tools.append("web_deep_research")
    if ("effort" in explicit and resolved["effort"] == "mission") or (
        "autonomy" in explicit and resolved["autonomy"] == "mission"
    ):
        forced_tools.append("long_task_start")
    if "output" in explicit and resolved["output"] == "document":
        forced_tools.append("document_generate")

    return {
        "version": 1,
        "requested": requested,
        "resolved": resolved,
        "explicit_axes": sorted(explicit),
        "forced_tools": list(dict.fromkeys(forced_tools)),
        "risk_score": risk_score(text),
        "reasons": reasons,
        "summary": summary(resolved),
    }


def risk_score(text: str) -> int:
    text = (text or "").lower()
    groups = [
        r"\b(production|serveur|pare-feu|réseau|ssh|powershell|script|déploiement)\b",
        r"\b(médical|juridique|finance|contrat|rgpd|sécurité)\b",
        r"\b(supprim|effac|envoi|publie|exécute|automatise)\w*",
        r"\b(critique|important|irréversible|urgent)\b",
    ]
    return sum(1 for pattern in groups if re.search(pattern, text))


def summary(resolved: dict) -> str:
    labels = {
        "instant": "instant", "standard": "standard", "deep": "approfondi", "mission": "mission",
        "none": "sans sources", "memory": "mémoire", "web": "web", "primary": "sources primaires",
        "connected": "sources connectées", "verify": "vérifié", "council_if_disagreement": "Council si désaccord",
        "council5": "Council 5", "search": "Cortex Search", "swarm": "Research Swarm",
        "team": "Équipe adaptative",
        "advise": "conseiller", "prepare": "préparer", "execute": "exécuter",
        "local": "local strict", "hybrid_redacted": "hybride privé", "cloud": "cloud",
        "chat": "chat", "brief": "synthèse", "report": "rapport", "document": "document",
        "table": "tableau", "workflow": "workflow",
    }
    keys = ("effort", "evidence", "review", "privacy", "output")
    values = [labels.get(resolved.get(k), resolved.get(k, "")) for k in keys]
    return " · ".join(v for v in values if v and v not in {"sans sources", "chat", "standard"}) or "Auto"


def prompt_block(compiled: dict) -> str:
    r = compiled["resolved"]
    lines = [
        "\n\n=== CONTRAT DE MISSION CORTEX ===",
        f"Effort={r['effort']}; preuves={r['evidence']}; révision={r['review']}; ",
        f"autonomie={r['autonomy']}; confidentialité={r['privacy']}; livrable={r['output']}.",
        "Ce contrat n'annule jamais les confirmations, permissions ou garde-fous existants.",
    ]
    if r["autonomy"] == "advise":
        lines.append("Reste en conseil : n'exécute aucune action sortante ou modificatrice.")
    elif r["autonomy"] == "prepare":
        lines.append("Prépare le résultat ou le plan ; toute action modificatrice doit rester proposée et confirmée.")
    if r["evidence"] in {"web", "primary", "connected"}:
        lines.append("Distingue les faits sourcés, les inférences et les points non résolus.")
    if r["evidence"] == "primary":
        lines.append("Privilégie les sources officielles ou primaires et cite-les au plus près des affirmations.")
    if r["output"] == "brief": lines.append("Livre une synthèse courte, orientée décision.")
    elif r["output"] == "report": lines.append("Livre un rapport structuré avec résumé, preuves, limites et recommandations.")
    elif r["output"] == "table": lines.append("Utilise un tableau seulement s'il rend la comparaison plus claire.")
    elif r["output"] == "workflow": lines.append("Propose un déroulé réutilisable, avec entrées, étapes et critères de réussite.")
    if r["privacy"] == "local": lines.append("Ce tour doit rester strictement sur un modèle local.")
    elif r["privacy"] == "hybrid_redacted":
        lines.append("Ne transmets jamais au cloud un secret ou une donnée brute sensible découverte par un outil.")
    return "\n".join(lines)


def provenance(
    compiled: dict, model: str, tools: set[str] | list[str], *, critique: bool = False,
    answer: str = "", conversation_id: str | None = None,
) -> dict:
    names = sorted(set(tools or []))
    evidence_tools = [n for n in names if n.startswith(("web_", "file_", "email_", "calendar_", "memory_"))]
    urls = list(dict.fromkeys(re.findall(r"https?://[^\s)\]>]+", answer or "")))[:20]
    requested_evidence = compiled["resolved"]["evidence"] in {"web", "primary", "connected"}
    ledger = None
    if conversation_id and answer.strip():
        try:
            import truth_ledger
            ledger = truth_ledger.record_response(
                conversation_id=conversation_id,
                answer=answer,
                citations=urls,
                evidence_tools=evidence_tools,
                reviewed=critique or "ai_model_council" in names or "ai_cortex_search" in names or "ai_research_swarm" in names or "ai_adaptive_team" in names or "ai_code_forge" in names,
            )
        except Exception:
            ledger = None
    return {
        "contract": compiled,
        "model": model,
        "tools": names,
        "evidence_tools": evidence_tools,
        "reviewed": critique or "ai_model_council" in names or "ai_cortex_search" in names or "ai_research_swarm" in names or "ai_adaptive_team" in names or "ai_code_forge" in names,
        "citations": urls,
        "evidence_coverage": (
            "cited" if urls else "tool_evidence" if evidence_tools else "missing" if requested_evidence else "not_requested"
        ),
        "privacy_route": compiled["resolved"]["privacy"],
        "unresolved": [],
        "truth_ledger": ({
            "record_id": ledger["id"],
            "claim_count": ledger["claim_count"],
            "sourced_count": ledger["sourced_count"],
            "unsupported_count": ledger["unsupported_count"],
            "epistemic_debt": ledger.get("epistemic_debt"),
            "source_firewall": ledger.get("source_firewall"),
        } if ledger else None),
    }


def _load_recipes() -> list[dict]:
    try:
        data = json.loads(_RECIPES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def list_recipes() -> list[dict]:
    with _LOCK:
        return deepcopy(_load_recipes())


def save_recipe(name: str, contract: dict, description: str = "") -> dict:
    name = _clean_text(name, 80)
    if not name:
        raise ValueError("Le nom de la recette est requis.")
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        recipes = _load_recipes()
        recipe = {
            "id": "cortex-" + uuid.uuid4().hex[:12],
            "name": name,
            "description": _clean_text(description, 240),
            "contract": normalize_contract(contract),
            "created_at": now,
            "updated_at": now,
        }
        recipes.append(recipe)
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _RECIPES_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(recipes, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _RECIPES_PATH)
        return deepcopy(recipe)


def delete_recipe(recipe_id: str) -> bool:
    with _LOCK:
        recipes = _load_recipes()
        kept = [r for r in recipes if r.get("id") != recipe_id]
        if len(kept) == len(recipes):
            return False
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _RECIPES_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _RECIPES_PATH)
        return True


def record_recipe_outcome(recipe_id: str | None, success: bool, tools: list[str] | set[str]) -> None:
    """Apprentissage borné : statistiques et plus courte trace d'outils réussie."""
    if not recipe_id:
        return
    with _LOCK:
        recipes = _load_recipes()
        changed = False
        for recipe in recipes:
            if recipe.get("id") != recipe_id:
                continue
            recipe["runs"] = int(recipe.get("runs") or 0) + 1
            recipe["successes"] = int(recipe.get("successes") or 0) + int(bool(success))
            trace = sorted(set(tools or []))
            old = recipe.get("best_tool_trace") or []
            if success and trace and (not old or len(trace) < len(old)):
                recipe["best_tool_trace"] = trace[:12]
            recipe["updated_at"] = datetime.now(timezone.utc).isoformat()
            changed = True
            break
        if changed:
            tmp = _RECIPES_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(recipes, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, _RECIPES_PATH)
