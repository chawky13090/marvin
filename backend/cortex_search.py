"""Cortex Search : exploration multi-stratégies et vérification spécialisée."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

import cloud_routing
import database as db
from config import OLLAMA_URL


STRATEGIES = (
    (
        "systémique",
        "Décompose le problème, identifie les dépendances et construis une solution complète de bout en bout.",
    ),
    (
        "conservatrice",
        "Privilégie la fiabilité, la réversibilité, les preuves et la réduction du risque opérationnel.",
    ),
    (
        "alternative",
        "Cherche une approche réellement différente, plus simple ou plus performante, puis expose ses compromis.",
    ),
)

VERIFIERS = (
    ("exactitude", "Vérifie la logique, les erreurs factuelles internes et les conclusions non démontrées."),
    ("preuves", "Vérifie la qualité des preuves, les affirmations à sourcer et les incertitudes."),
    ("contraintes", "Vérifie le respect exact de la demande, des interdictions et du contexte utilisateur."),
    ("risques", "Vérifie les effets de bord, les cas limites, la sécurité, le rollback et les échecs possibles."),
    ("exécution", "Vérifie que la solution est concrète, testable, ordonnée et exploitable en production."),
)


def validate_runtime(question: str, evidence: str = "") -> tuple[str | None, list[str]]:
    question = (question or "").strip()
    if not question:
        return "Paramètre 'question' requis.", []
    enabled, _ = cloud_routing.get_cloud_config()
    if not enabled:
        return "Le mode cloud n'est pas activé ; Cortex Search exige Ollama Cloud.", []
    if cloud_routing.is_local_only_lockdown():
        return "Le mode Hyper local interdit Cortex Search Cloud.", []
    if cloud_routing.is_sensitive_text(question + "\n" + evidence) and not cloud_routing.is_ultra_unrestricted():
        return "Donnée sensible détectée : Cortex Search Cloud est bloqué hors mode Ultra débridé.", []
    models = cloud_routing.list_distinct_cloud_models(cloud_routing.detect_task(question) or "general")
    if len(models) < 5:
        return f"Cortex Search requiert cinq familles cloud distinctes ; {len(models)} disponible(s).", models
    return None, models


async def execute(question: str, evidence: str = "", candidate_count: int = 3) -> dict[str, Any]:
    error, models = validate_runtime(question, evidence)
    if error:
        return {"error": error, "available_models": models}

    candidate_count = max(2, min(int(candidate_count), len(STRATEGIES)))
    try:
        concurrency = max(1, min(int(db.get_setting("cortex_search_concurrency") or 4), 5))
    except Exception:
        concurrency = 4
    semaphore = asyncio.Semaphore(concurrency)

    async def call(client: httpx.AsyncClient, model: str, prompt: str, phase: str) -> dict[str, Any]:
        started = time.perf_counter()
        errors: list[str] = []
        async with semaphore:
            for attempt in range(1, 3):
                try:
                    response = await client.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False},
                    )
                    response.raise_for_status()
                    answer = str(response.json().get("response") or "").strip()
                    if not answer:
                        raise RuntimeError("réponse vide")
                    return {
                        "ok": True,
                        "model": model,
                        "family": cloud_routing.model_family(model),
                        "phase": phase,
                        "answer": answer,
                        "attempts": attempt,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {str(exc)[:180]}")
                    if isinstance(exc, httpx.TimeoutException):
                        break
                    if attempt == 1:
                        await asyncio.sleep(0.5)
        return {
            "ok": False,
            "model": model,
            "family": cloud_routing.model_family(model),
            "phase": phase,
            "errors": errors,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }

    evidence_block = f"\n\nÉLÉMENTS FOURNIS :\n{evidence[:12000]}" if evidence else ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        candidate_jobs = []
        for index, (name, instruction) in enumerate(STRATEGIES[:candidate_count]):
            candidate_jobs.append(
                call(
                    client,
                    models[index],
                    (
                        f"Tu explores la stratégie {name}. {instruction}\n"
                        "Produis une solution indépendante en français. Structure : Hypothèses, Approche, "
                        "Étapes, Vérifications, Risques, Limites et Confiance 0-100. "
                        "Ne prétends pas avoir vérifié une information absente des éléments fournis.\n\n"
                        f"PROBLÈME :\n{question}{evidence_block}"
                    ),
                    "candidate",
                )
            )
        candidates = list(await asyncio.gather(*candidate_jobs))
        successful_candidates = [item for item in candidates if item.get("ok")]
        if len(successful_candidates) < 2:
            return {"error": "Cortex Search n'a pas obtenu au moins deux stratégies valides.", "candidates": candidates}

        anonymous = [
            {"id": chr(65 + index), "answer": item["answer"][:6500]}
            for index, item in enumerate(successful_candidates)
        ]
        digest = "\n\n".join(f"[CANDIDAT {item['id']}]\n{item['answer']}" for item in anonymous)
        verifier_jobs = []
        for index, (aspect, instruction) in enumerate(VERIFIERS):
            verifier_jobs.append(
                call(
                    client,
                    models[index],
                    (
                        f"Tu es vérificateur spécialisé en {aspect}. {instruction}\n"
                        "Compare les candidats sans voter par popularité. Réponds avec : Défauts par candidat, "
                        "meilleur candidat pour cet aspect, corrections obligatoires, éléments non vérifiés et "
                        "niveau de confiance 0-100.\n\n"
                        f"PROBLÈME :\n{question}\n\n{digest}"
                    ),
                    f"verify_{aspect}",
                )
            )
        verifications = list(await asyncio.gather(*verifier_jobs))
        successful_verifications = [item for item in verifications if item.get("ok")]
        if len(successful_verifications) < 3:
            return {
                "error": "Cortex Search n'a pas obtenu assez de vérifications spécialisées.",
                "candidates": candidates,
                "verifications": verifications,
            }

        reviews = "\n\n".join(
            f"[VÉRIFICATEUR {VERIFIERS[index][0]}]\n{item.get('answer', 'indisponible')[:5000]}"
            for index, item in enumerate(verifications)
        )
        synthesis_prompt = (
            "Tu es l'arbitre Cortex Search. Sélectionne et améliore la meilleure stratégie en utilisant les "
            "vérifications spécialisées. Ne fabrique pas de consensus : conserve les désaccords qui changent "
            "la décision. La réponse finale doit contenir : Décision, Raisons, Plan ordonné, Vérifications "
            "objectives, Risques et rollback, Incertitudes, Alternatives rejetées et Confiance globale 0-100.\n\n"
            f"PROBLÈME :\n{question}\n\nCANDIDATS :\n{digest}\n\nREVUES :\n{reviews}"
        )
        arbitration = await call(client, models[0], synthesis_prompt, "arbitration")
        if not arbitration.get("ok"):
            for fallback_model in models[1:]:
                arbitration = await call(client, fallback_model, synthesis_prompt, "arbitration_fallback")
                if arbitration.get("ok"):
                    break
        if not arbitration.get("ok"):
            return {
                "error": "Exploration et vérification terminées, mais l'arbitrage a échoué.",
                "candidates": candidates,
                "verifications": verifications,
            }

    return {
        "success": True,
        "answer": arbitration["answer"],
        "candidate_count": len(successful_candidates),
        "verifier_count": len(successful_verifications),
        "candidates": successful_candidates,
        "verifications": successful_verifications,
        "arbitration": arbitration,
        "models_consulted": sorted({item["model"] for item in successful_candidates + successful_verifications}),
        "families": sorted({item["family"] for item in successful_candidates + successful_verifications}),
        "concurrency": concurrency,
        "privacy_mode": "ultra_unrestricted" if cloud_routing.is_ultra_unrestricted() else "cloud_non_sensitive",
        "message": "Cortex Search terminé : stratégies indépendantes, cinq vérificateurs et arbitrage.",
    }
