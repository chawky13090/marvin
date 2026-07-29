"""Council Cloud à cinq familles : panel parallèle, critique et arbitrage traçable."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx


_routing: Any = None
_get_setting: Callable[[str], Any] | None = None
_ollama_url = ""
_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient
_sleep: Callable[[float], Any] = asyncio.sleep
_id_factory: Callable[[], str] = lambda: f"council-{uuid.uuid4().hex[:12]}"

_PANEL_SIZE = 5
_MAX_QUESTION_CHARS = 50_000
_MAX_EVIDENCE_CHARS = 12_000
_MAX_ANSWER_CHARS = 30_000
_ROLES = (
    ("analyste", "Construis la meilleure solution et explicite les hypothèses décisives."),
    ("critique", "Cherche les erreurs, contre-exemples, risques et hypothèses cachées."),
    ("vérificateur", "Contrôle la solidité factuelle, les preuves et ce qui reste incertain."),
    ("alternatif", "Propose une approche réellement différente et compare ses compromis."),
    ("praticien", "Transforme l'analyse en décision concrète, testable et priorisée."),
)


def configure(
    *,
    routing: Any,
    get_setting: Callable[[str], Any],
    ollama_url: str,
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    sleep: Callable[[float], Any] = asyncio.sleep,
    id_factory: Callable[[], str] | None = None,
) -> None:
    global _routing, _get_setting, _ollama_url, _client_factory, _sleep, _id_factory
    _routing = routing
    _get_setting = get_setting
    _ollama_url = str(ollama_url).rstrip("/")
    _client_factory = client_factory
    _sleep = sleep
    if id_factory is not None:
        _id_factory = id_factory


def _dependencies() -> tuple[Any, Callable[[str], Any]]:
    if _routing is None or _get_setting is None or not _ollama_url:
        raise RuntimeError("Le moteur Council n'est pas configuré.")
    return _routing, _get_setting


def _validated_text(args: dict) -> tuple[str, str] | dict:
    question = str(args.get("question") or args.get("query") or "").strip()
    if not question:
        return {"error": "Paramètre 'question' requis."}
    if len(question) > _MAX_QUESTION_CHARS:
        return {"error": f"La question dépasse {_MAX_QUESTION_CHARS} caractères."}
    evidence = str(args.get("evidence") or args.get("context") or "").strip()
    if len(evidence) > _MAX_EVIDENCE_CHARS:
        return {"error": f"Les éléments vérifiés dépassent {_MAX_EVIDENCE_CHARS} caractères."}
    return question, evidence


async def run(args: dict) -> dict:
    """Consulte cinq familles Cloud, puis réalise critique aveugle et arbitrage."""
    validated = _validated_text(args)
    if isinstance(validated, dict):
        return validated
    question, evidence = validated
    try:
        routing, get_setting = _dependencies()
        cloud_enabled, _ = routing.get_cloud_config()
        if not cloud_enabled:
            return {
                "error": (
                    "Le mode cloud n'est pas activé — Council exige cinq modèles "
                    "Ollama Cloud."
                )
            }
        if routing.is_local_only_lockdown():
            return {
                "error": (
                    "Le mode Hyper local interdit Council Cloud. Passe en mode Normal, "
                    "Tout cloud ou Ultra débridé."
                )
            }
        sensitive = routing.is_sensitive_text(question + "\n" + evidence)
        if sensitive and not routing.is_ultra_unrestricted():
            return {
                "error": (
                    "Donnée sensible détectée : les cinq avis cloud sont bloqués "
                    "hors mode Ultra débridé."
                )
            }
        need = routing.detect_task(question) or "general"
        candidates = list(routing.list_distinct_cloud_models(need))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"error": f"Configuration Council invalide : {exc}"}

    if len(candidates) < _PANEL_SIZE:
        return {
            "error": (
                f"Council requiert 5 familles cloud distinctes ; "
                f"{len(candidates)} seulement sont disponibles."
            ),
            "available_models": candidates,
        }
    selected = candidates[:_PANEL_SIZE]
    selected_families = [routing.model_family(model) for model in selected]
    if len(set(selected_families)) != _PANEL_SIZE:
        return {
            "error": "La sélection Council ne contient pas cinq familles distinctes.",
            "available_models": candidates,
        }
    try:
        concurrency = max(
            1,
            min(int(get_setting("council_concurrency") or 3), _PANEL_SIZE),
        )
    except (TypeError, ValueError):
        concurrency = 3
    council_id = _id_factory()
    semaphore = asyncio.Semaphore(concurrency)

    async def cloud_call(
        client: httpx.AsyncClient,
        model: str,
        prompt: str,
        phase: str,
    ) -> dict:
        started = time.perf_counter()
        errors: list[str] = []
        async with semaphore:
            for attempt in range(1, 3):
                try:
                    response = await client.post(
                        f"{_ollama_url}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    answer = str(payload.get("response") or "").strip()
                    if not answer:
                        raise RuntimeError("réponse vide")
                    truncated = len(answer) > _MAX_ANSWER_CHARS
                    return {
                        "ok": True,
                        "model": model,
                        "family": routing.model_family(model),
                        "source": "ollama_cloud",
                        "phase": phase,
                        "answer": answer[:_MAX_ANSWER_CHARS],
                        "answer_truncated": truncated,
                        "attempts": attempt,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                except (
                    httpx.HTTPError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ) as exc:
                    errors.append(f"{type(exc).__name__}: {str(exc)[:180]}")
                    if isinstance(exc, httpx.TimeoutException):
                        break
                    if attempt == 1:
                        await _sleep(0.5)
        return {
            "ok": False,
            "model": model,
            "family": routing.model_family(model),
            "source": "ollama_cloud",
            "phase": phase,
            "attempts": len(errors),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "errors": errors,
        }

    context_block = (
        f"\n\nÉLÉMENTS VÉRIFIÉS FOURNIS :\n{evidence}" if evidence else ""
    )
    timeout = httpx.Timeout(150.0, connect=10.0)
    async with _client_factory(timeout=timeout) as client:
        prompts = [
            (
                model,
                f"Tu es le membre {index + 1} d'un conseil, rôle : {role}. "
                f"{instruction}\nTravaille indépendamment : ne suppose pas ce que diront "
                "les autres. Réponds en français avec les sections Recommandation, Raisons, "
                "Preuves ou vérifications nécessaires, Risques, Incertitudes et Confiance "
                f"(0-100).\n\nQUESTION :\n{question}{context_block}",
            )
            for index, ((role, instruction), model) in enumerate(zip(_ROLES, selected))
        ]
        results = list(
            await asyncio.gather(
                *[
                    cloud_call(client, model, prompt, "independent")
                    for model, prompt in prompts
                ]
            )
        )
        attempt_log: list[dict] = []
        for index, result in enumerate(results):
            result["slot"] = index + 1
            result["role"] = _ROLES[index][0]
            attempt_log.append(dict(result))

        reserve = candidates[_PANEL_SIZE:]
        for index, result in enumerate(list(results)):
            if result.get("ok"):
                continue
            while reserve:
                replacement = reserve.pop(0)
                retried = await cloud_call(
                    client,
                    replacement,
                    prompts[index][1],
                    "independent_replacement",
                )
                retried["slot"] = index + 1
                retried["role"] = _ROLES[index][0]
                attempt_log.append(dict(retried))
                results[index] = retried
                if retried.get("ok"):
                    break

        successful = [item for item in results if item.get("ok")]
        families = {routing.model_family(item["model"]) for item in successful}
        if len(successful) != _PANEL_SIZE or len(families) != _PANEL_SIZE:
            return {
                "error": (
                    "Impossible d'obtenir cinq réponses cloud issues de cinq "
                    "familles distinctes."
                ),
                "council_id": council_id,
                "attempted": attempt_log,
            }

        anonymous = [
            {"id": chr(65 + index), "answer": item["answer"][:4500]}
            for index, item in enumerate(successful)
        ]
        forward_digest = "\n\n".join(
            f"[AVIS {item['id']}]\n{item['answer']}" for item in anonymous
        )
        critic_prompt = (
            "Tu es le contradicteur d'un conseil. Les avis sont anonymisés : ne devine pas "
            "les modèles. Identifie les affirmations non étayées, contradictions, consensus "
            "trompeurs et l'avis minoritaire qui pourrait être juste. Termine par les "
            f"critères que l'arbitre doit appliquer.\n\nQUESTION : {question}\n\n"
            f"{forward_digest}"
        )
        critique = await cloud_call(
            client,
            successful[3]["model"],
            critic_prompt,
            "cross_critique",
        )
        reverse_digest = "\n\n".join(
            f"[AVIS {item['id']}]\n{item['answer']}"
            for item in reversed(anonymous)
        )
        judge_prompt = (
            "Tu es l'arbitre final. Les cinq avis sont anonymisés et présentés dans un ordre "
            "inversé par rapport au contradicteur. Ne vote pas à la majorité : juge les "
            "preuves, le respect des contraintes, les risques et l'applicabilité. Préserve "
            "explicitement un désaccord important au lieu de fabriquer un consensus. Réponds "
            "en français avec : Réponse retenue, Pourquoi, Consensus solide, Désaccords, "
            "Incertitudes, Plan d'action et Confiance globale (0-100).\n\n"
            f"QUESTION : {question}\n\nAVIS :\n{reverse_digest}\n\n"
            f"REVUE CONTRADICTOIRE :\n"
            f"{critique.get('answer', 'indisponible')[:5000]}"
        )
        arbitration = None
        for judge in (successful[0], successful[2], successful[1], successful[4]):
            attempt = await cloud_call(
                client,
                judge["model"],
                judge_prompt,
                "arbitration",
            )
            if attempt.get("ok"):
                arbitration = attempt
                break
        if arbitration is None:
            return {
                "error": (
                    "Les cinq avis ont répondu, mais l'arbitrage cloud a échoué."
                ),
                "council_id": council_id,
                "panel": successful,
            }

    return {
        "success": True,
        "council_id": council_id,
        "answer": arbitration["answer"],
        "models_consulted": [item["model"] for item in successful],
        "families": [item["family"] for item in successful],
        "panel_size": _PANEL_SIZE,
        "concurrency": concurrency,
        "individual_answers": successful,
        "panel_attempt_log": attempt_log,
        "critique": critique,
        "arbitration": arbitration,
        "privacy_mode": (
            "ultra_unrestricted"
            if routing.is_ultra_unrestricted()
            else "cloud_non_sensitive"
        ),
        "privacy_preset": routing.get_privacy_preset(),
        "message": (
            "Council terminé : 5 familles cloud, critique croisée et "
            "arbitrage traçable."
        ),
    }
