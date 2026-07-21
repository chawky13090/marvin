"""Adaptive Team Runtime: bounded composition of Marvin's strongest reasoning engines."""
from __future__ import annotations

import re
import time
from typing import Any

import cloud_routing


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, flags=re.I))


def plan(question: str) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(question or "")).strip()
    research = _has(
        r"\b(cherche|recherche|sources?|documentation|web|internet|actuel|récent|étudie|benchmark)\w*",
        text,
    )
    technical = _has(
        r"\b(architecture|diagnostic|code|projet|système|réseau|déploiement|performance|optimis|implément)\w*",
        text,
    )
    decision = _has(
        r"\b(compare|choisir|choix|décision|meilleur|stratégie|alternative|compromis|prioris)\w*",
        text,
    )
    high_stakes = _has(
        r"\b(production|sécurité|juridique|médical|finance|critique|irréversible|migration)\w*",
        text,
    )
    depth = _has(
        r"\b(approfond|exhausti|complexe|expert|réfléchis mieux|en profondeur|plus puissant)\w*",
        text,
    )
    code_delivery = _has(
        r"\b(script|programme|code complet|powershell|bash|python|fichier\s+\.(?:ps1|sh|py|js))\b",
        text,
    ) and _has(
        r"\b(crée|cree|génère|genere|écris|ecris|développe|developpe|corrige|"
        r"améliore|ameliore|audite|sécurise|securise|installation|déploiement|deploiement)\b",
        text,
    )
    fresh_code_evidence = code_delivery and _has(
        r"\b(install|installation|déploiement|deploiement|paquet|package|dépôt|depot|"
        r"repository|version|compatible|conforme|sécurisé|securise|meilleures pratiques)\w*",
        text,
    )
    research = research or fresh_code_evidence
    constraints = len(re.findall(r"\b(et|mais|sans|avec|doit|devrait|uniquement|hormis)\b", text, flags=re.I))
    complexity = min(
        10,
        int(research) * 2 + int(technical) * 2 + int(decision) * 2
        + int(high_stakes) * 2 + int(depth) * 2 + min(constraints, 2)
        + int(len(text) >= 180),
    )
    if code_delivery and research:
        pipeline = ["research_swarm", "code_forge"]
        reason = "recherche des versions et pratiques puis livraison de code expert"
    elif code_delivery:
        pipeline = ["code_forge"]
        reason = "architecture, double revue, réparation et validation du code"
    elif research and (technical or decision or complexity >= 6):
        pipeline = ["research_swarm", "cortex_search"]
        reason = "recherche actuelle puis résolution multi-stratégies"
    elif research:
        pipeline = ["research_swarm"]
        reason = "collecte et contradiction de sources"
    elif technical or complexity >= 5:
        pipeline = ["cortex_search"]
        reason = "exploration de stratégies et vérification spécialisée"
    else:
        pipeline = ["model_council"]
        reason = "jugement multi-modèle sans recherche web obligatoire"
    return {
        "version": 1,
        "question": text,
        "pipeline": pipeline,
        "complexity": complexity,
        "signals": {
            "research": research,
            "technical": technical,
            "decision": decision,
            "high_stakes": high_stakes,
            "depth": depth,
            "code_delivery": code_delivery,
            "fresh_code_evidence": fresh_code_evidence,
            "constraint_count": constraints,
        },
        "reason": reason,
        "budgets": {
            "max_stages": 2,
            "max_duration_seconds": 1200,
            "research_agents": 5 if complexity >= 7 else 3,
            "cortex_candidates": 3 if complexity >= 6 else 2,
        },
    }


def should_auto_activate(question: str) -> bool:
    text = re.sub(r"\s+", " ", str(question or "")).strip()
    if len(text) < 60:
        return False
    explicit_depth = _has(
        r"\b(équipe d'experts|plusieurs experts|multi[- ]?modèles|réfléchis mieux|"
        r"analyse approfondie|étude approfondie|en profondeur|exhaustif|place toi au dessus)\b",
        text,
    )
    selected = plan(text)
    return explicit_depth and selected["complexity"] >= 5


def validate_runtime(question: str) -> str | None:
    if not str(question or "").strip():
        return "Paramètre 'question' requis."
    enabled, _ = cloud_routing.get_cloud_config()
    if not enabled:
        return "Adaptive Team exige Ollama Cloud activé."
    if cloud_routing.is_local_only_lockdown():
        return "Le mode Hyper local interdit Adaptive Team Cloud."
    if cloud_routing.is_sensitive_text(question) and not cloud_routing.is_ultra_unrestricted():
        return "Donnée sensible détectée : Adaptive Team Cloud est bloqué hors mode Ultra débridé."
    return None


async def execute(question: str) -> dict[str, Any]:
    error = validate_runtime(question)
    team_plan = plan(question)
    if error:
        return {"error": error, "team_plan": team_plan}
    started = time.perf_counter()
    stages = []
    accumulated_evidence = ""
    final_answer = ""
    models: set[str] = set()
    families: set[str] = set()

    for stage_name in team_plan["pipeline"][:team_plan["budgets"]["max_stages"]]:
        if stage_name == "research_swarm":
            import research_swarm
            result = await research_swarm.execute(
                question,
                agent_count=team_plan["budgets"]["research_agents"],
                sources_per_agent=3,
                max_duration_seconds=min(900, team_plan["budgets"]["max_duration_seconds"]),
            )
        elif stage_name == "cortex_search":
            import cortex_search
            result = await cortex_search.execute(
                question,
                evidence=accumulated_evidence[:12000],
                candidate_count=team_plan["budgets"]["cortex_candidates"],
            )
        elif stage_name == "code_forge":
            import code_forge
            result = await code_forge.execute(
                question,
                evidence=accumulated_evidence[:30000],
            )
        else:
            import tools
            result = await tools.execute_ai_model_council({
                "question": question,
                "evidence": accumulated_evidence[:12000],
            })
        stage = {
            "name": stage_name,
            "success": bool(result.get("success")) and not result.get("error"),
            "error": result.get("error"),
            "answer": str(result.get("answer") or "")[:20000],
            "models_consulted": result.get("models_consulted") or [],
            "families": result.get("families") or [],
            "evidence_fabric": result.get("evidence_fabric"),
            "deliverable_gate": ({
                "language": result.get("language"),
                "syntax_valid": (result.get("validation") or {}).get("syntax_valid"),
                "validation_success": (result.get("validation") or {}).get("success"),
                "failed_checks": (result.get("validation") or {}).get("failed_checks") or [],
                "final_score": (result.get("final_review") or {}).get("score"),
                "final_review_valid": (result.get("final_review") or {}).get("valid"),
                "final_review_ok": (result.get("final_review") or {}).get("ok"),
                "final_verdict": (result.get("final_review") or {}).get("verdict"),
                "final_issues": (result.get("final_review") or {}).get("issues") or [],
                "critical_issues": result.get("critical_issues"),
                "high_issues": result.get("high_issues"),
                "gate_repair_attempts": len(result.get("gate_repair_attempts") or []),
                "gate_reviews": result.get("gate_reviews") or [],
                "final_gate_attempts": len(result.get("final_gate_attempts") or []),
                "final_gate_error": (result.get("final_review") or {}).get("error"),
                "code_length": len(str(result.get("code") or "")),
                "test_forge_ready": (result.get("test_report") or {}).get("production_ready"),
                "test_forge_steps": [
                    {
                        "name": item.get("name"),
                        "passed": item.get("passed"),
                        "exit_code": item.get("exit_code"),
                    }
                    for item in (result.get("test_report") or {}).get("steps", [])
                ],
            } if stage_name == "code_forge" else None),
        }
        fabric = stage["evidence_fabric"] if isinstance(stage["evidence_fabric"], dict) else {}
        semantic = fabric.get("semantic_verification") if isinstance(fabric.get("semantic_verification"), dict) else {}
        debt = (fabric.get("epistemic_debt") or {}).get("score") if fabric else None
        stage["evidence_quality"] = {
            "epistemic_debt": debt,
            "supported": int(semantic.get("supported") or 0),
            "contradicted": int(semantic.get("contradicted") or 0),
            "disputed": int(semantic.get("disputed") or 0),
            "insufficient": int(semantic.get("insufficient") or 0),
        } if fabric else None
        stages.append(stage)
        models.update(str(item) for item in stage["models_consulted"])
        families.update(str(item) for item in stage["families"])
        if stage["success"] and stage["answer"]:
            final_answer = stage["answer"]
            quality_block = ""
            if stage["evidence_quality"]:
                quality = stage["evidence_quality"]
                quality_block = (
                    "\n\nQUALITÉ DES PREUVES : "
                    f"dette={quality['epistemic_debt']}; soutenues={quality['supported']}; "
                    f"contredites={quality['contradicted']}; disputées={quality['disputed']}; "
                    f"insuffisantes={quality['insufficient']}. "
                    "Ne reprends pas comme fait une affirmation insuffisante, contredite ou disputée."
                )
            stage_context = str(result.get("evidence_context") or stage["answer"])
            accumulated_evidence = (
                f"DOSSIER DE L'ÉTAPE {stage_name} :\n"
                f"{stage_context[:30000]}{quality_block}"
            )
        elif not final_answer:
            continue

    successful = [item for item in stages if item["success"]]
    if not successful:
        return {
            "error": "Adaptive Team n'a obtenu aucune étape valide.",
            "team_plan": team_plan,
            "stages": stages,
        }
    if stages and not stages[-1]["success"]:
        return {
            "error": (
                f"Adaptive Team a terminé les étapes préparatoires, mais le livrable final "
                f"'{stages[-1]['name']}' a échoué : {stages[-1].get('error') or 'gate de qualité refusé'}."
            ),
            "team_plan": team_plan,
            "stages": stages,
            "partial_successes": len(successful),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
    return {
        "success": True,
        "answer": final_answer,
        "team_plan": team_plan,
        "stages": stages,
        "models_consulted": sorted(models),
        "families": sorted(families),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "evidence_quality": next(
            (item["evidence_quality"] for item in reversed(stages) if item.get("evidence_quality")),
            None,
        ),
        "privacy_mode": "ultra_unrestricted" if cloud_routing.is_ultra_unrestricted() else "cloud_non_sensitive",
        "message": f"Adaptive Team terminé : {len(successful)}/{len(stages)} étape(s) valide(s).",
    }
