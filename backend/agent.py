"""
SecretaryAI Backend — Runner agentique de streaming.
Orchestre Ollama via l'adaptateur de transport, gère la boucle d'appel d'outils
et produit les événements SSE du frontend.
"""
import asyncio
import re
from typing import AsyncIterator

import cloud_routing as _cr
import cortex as _cortex
import database as db
from intent_guard import skill_match_text
from agent_prompt import build_system_prompt as _build_system_prompt
from agent_protocol import encode_sse as _sse, to_ollama_messages as _to_ollama_messages
from agent_routing import (
    SENSITIVE_TOOL_PREFIXES as _SENSITIVE_TOOL_PREFIXES,
    detect_profile as _detect_profile,
    get_cloud_config as _get_cloud_config,
    is_cloud_model as _is_cloud_model,
    is_local_only_lockdown as _is_local_only_lockdown,
    is_sensitive_request as _is_sensitive_request,
    is_sensitive_tool as _is_sensitive_tool,
    is_ultra_unrestricted as _is_ultra_unrestricted,
    pick_available as _pick_available,
    refresh_model_cache as _refresh_model_cache,
)
from agent_safety import (
    scan_dangerous_script_patterns as _scan_dangerous_script_patterns,
    validator_for,
)
from agent_execution import (
    execute_registered_tool as _execute_registered_tool,
    is_tooling_failure as _is_tooling_failure,
    log_tool_exception as _log_tool_exception,
    salvage_text_tool_calls as _salvage_text_tool_calls,
)
from agent_review import (
    review_action as _critique_action,
    review_response as _run_critique_pass,
)
from agent_context import (
    persist_and_analyze_screenshot as _persist_and_analyze_one_screenshot,
    persist_and_analyze_screenshots as _persist_and_analyze_screenshots,
    summarize_overflow as _conversation_summary,
)
from agent_session import prepare_turn as _prepare_turn, upgrade_title as _smart_title_upgrade
from agent_planning import compile_turn_plan as _compile_turn_plan
from agent_model_config import resolve_model_config as _resolve_model_config
from agent_runner import RunnerState as _RunnerState
from agent_observability import (
    record_long_chain as _record_long_chain,
    record_tool_observation as _record_tool_observation,
)
from agent_finalization import finalize_answer as _finalize_answer
from agent_required_tools import (
    RequiredToolContext as _RequiredToolContext,
    inject_required_tool_calls as _inject_required_tool_calls,
)
from agent_tool_step import (
    compact_tool_result as _compact_tool_result,
    inject_internal_context as _inject_internal_tool_context,
    prepare_tool_call as _prepare_tool_call,
)
from agent_tool_dispatch import (
    ALWAYS_CONFIRM_TOOLS as _ALWAYS_CONFIRM_TOOLS,
    EXECUTION_TOOLS as _EXECUTION_TOOLS,
    dispatch_tool as _dispatch_tool,
)
from agent_tool_postprocess import (
    postprocess_tool_result as _postprocess_tool_result,
)
from agent_skill_outcome import SkillOutcomeRecorder as _SkillOutcomeRecorder
from agent_council_escalation import (
    escalate_council_on_disagreement as _escalate_council_on_disagreement,
)
from agent_learning import schedule_exchange_learning as _schedule_exchange_learning
from agent_turn_context import prepare_agent_context as _prepare_agent_context
from agent_enrichment import (
    assemble_tool_payload as _assemble_tool_payload,
    inject_learned_block as _inject_learned_block,
    start_enrichments as _start_enrichments,
)
from agent_skill_context import build_skill_prompt_context as _build_skill_prompt_context
from agent_model_step import (
    ModelStepResult as _ModelStepResult,
    prepare_model_step as _prepare_model_step,
    stream_model_step as _stream_model_step,
)
from agent_tool_batch import execute_tool_batch as _execute_tool_batch
from agent_transport import (
    OllamaChatRequest as _OllamaChatRequest,
    create_client as _create_ollama_client,
    error_event as _ollama_error_event,
    stream_chat as _stream_ollama_chat,
)
from agent_tool_selection import filter_relevant_tools as _filter_relevant_tools
from config import (
    OLLAMA_URL, MAX_CONTEXT_MESSAGES,
    DEFAULT_PERMISSION_LEVEL, DANGEROUS_TOOLS,
    MODEL_PROFILES,
)
from tools import TOOLS_REGISTRY, TOOLS_SPEC

_validate_tool_args = validator_for(TOOLS_SPEC)

# Conserve les références des tâches d'apprentissage en arrière-plan (anti-GC).
_BG_LEARN_TASKS: set = set()

# ── Agent de streaming principal ──────────────────────────────────────────────

async def run_agent(
    messages: list[dict],
    conversation_id: str | None,
    model: str | None,
    cortex_contract: dict | None = None,
    request_id: str | None = None,
) -> AsyncIterator[str]:
    """
    Générateur SSE. Yielde des événements de type :
      conv_id   — identifiant de conversation (nouvelles conversations)
      text      — fragment de texte streamé
      tool_start — début d'appel d'outil
      tool_end   — fin d'appel d'outil avec résultat
      done       — fin de génération
      error      — erreur fatale
    """
    _prepared_turn = await _prepare_turn(
        messages,
        conversation_id,
        request_id,
        background_tasks=_BG_LEARN_TASKS,
    )
    conversation_id = _prepared_turn.conversation_id
    _user_query = _prepared_turn.user_query
    for _turn_event in _prepared_turn.events:
        yield _sse(_turn_event)
    _turn_plan = _compile_turn_plan(messages, _user_query, cortex_contract)
    _explicit_tool_names = _turn_plan.explicit_tool_names
    _command_text_only = _turn_plan.command_text_only
    _tool_suppression = _turn_plan.tool_suppression
    _required_tool_names = _turn_plan.required_tool_names
    _workspace_norm = _turn_plan.workspace_norm
    _workspace_route = _turn_plan.workspace_route
    _workspace_mission_id = _turn_plan.workspace_mission_id
    _workspace_action = _turn_plan.workspace_action
    _cortex_plan = _turn_plan.cortex_plan
    _max_tool_steps = _turn_plan.max_tool_steps
    _max_wall_seconds = _turn_plan.max_wall_seconds
    yield _sse({"type": "cortex_contract", "contract": _cortex_plan})

    try:
        _model_config = await _resolve_model_config(
            messages, _user_query, model, _cortex_plan
        )
    except _cr.CloudOnlyModelUnavailable as exc:
        yield _sse({"type": "error", "message": str(exc), "cloud_only": True})
        return
    profile_name = _model_config.profile_name
    active_model = _model_config.active_model
    temperature = _model_config.temperature
    _lockdown = _model_config.lockdown
    _ultra = _model_config.ultra_cloud_only

    _local_fallback_model = _model_config.local_fallback_model
    yield _sse(_model_config.event())

    # ── Préparer les messages pour Ollama ────────────────────────────────────
    # Profondeur de mémoire conversationnelle pilotée par le MODE (plus de contexte sur
    # une machine puissante, moins sur une petite pour rester rapide).
    from tools import execute_pc_get_real_paths

    _base_context = await _prepare_agent_context(
        messages=messages,
        conversation_id=conversation_id,
        profile_name=profile_name,
        cortex_plan=_cortex_plan,
        tool_suppression=_tool_suppression,
        required_tool_names=_required_tool_names,
        max_context_messages=MAX_CONTEXT_MESSAGES,
        default_permission_level=DEFAULT_PERMISSION_LEVEL,
        model_profiles=MODEL_PROFILES,
        get_setting=db.get_setting,
        get_memories=db.get_memories,
        get_conversation=db.get_conversation,
        get_project=db.get_project,
        to_ollama_messages=_to_ollama_messages,
        build_system_prompt=_build_system_prompt,
        cortex_prompt_block=_cortex.prompt_block,
        get_real_paths=execute_pc_get_real_paths,
    )
    _overflow = _base_context.overflow
    ollama_msgs = _base_context.ollama_messages
    system_prompt = _base_context.system_prompt
    permission_level = _base_context.permission_level
    use_tools = _base_context.use_tools

    # Connaissances apprises : rappel SÉMANTIQUE → injecté EN TÊTE (priorité absolue,
    # sinon noyé dans le long prompt de capacités et ignoré par le modèle).
    # Rappel mémoire (embed) + filtrage des outils (embed) = 2 opérations INDÉPENDANTES.
    # On les lance EN PARALLÈLE (gain de latence, résultat identique) et on construit le
    # prompt système pendant ce temps.
    _enrichments = _start_enrichments(
        messages=messages,
        user_query=_user_query,
        profile_name=profile_name,
        use_tools=use_tools,
        tool_suppression=_tool_suppression,
        skill_matcher_text=skill_match_text,
        filter_tools=_filter_relevant_tools,
    )

    # SKILL : si une compétence (fichier Markdown) correspond à la demande, on injecte sa
    # MÉTHODE dans le prompt (Marvin l'applique avec ses outils déjà vérifiés). Couche-prompt
    # uniquement → aucune exécution de code, donc aucune faille « à la OpenClaw ».
    _skill = await _enrichments.skill()
    if _skill:
        import skills as _skills_context

        _skill_context = _build_skill_prompt_context(
            system_prompt,
            _skill,
            get_golden_trace=_skills_context.get_golden_trace,
            resources_prompt_block=_skills_context.resources_prompt_block,
        )
        if not _skill_context.valid:
            _skill = None
        else:
            system_prompt = _skill_context.prompt
        # Une compétence pilote des OUTILS → un petit modèle (chat 3b) suit mal la méthode et
        # choisit le mauvais outil. On bascule sur le modèle AGENT (plus fiable) pour l'exécuter.
        if _skill and profile_name == "chat" and _skill_context.requires_agent_profile:
            profile_name = "agent"
            _agent_local = _pick_available(
                MODEL_PROFILES.get("agent", {}).get("model", active_model),
                AUTO_MODE_FALLBACKS,
            )
            try:
                active_model = _cr.resolve_model(
                    None,
                    profile="agent",
                    local_fallback=_agent_local,
                    text_for_sensitivity=_user_query,
                )
            except _cr.CloudOnlyModelUnavailable as exc:
                await _enrichments.cancel_pending()
                yield _sse({"type": "error", "message": str(exc), "cloud_only": True})
                return
            yield _sse({"type": "model_info", "profile": "agent", "model": active_model,
                        "label": (f"☁️ Cloud strict · compétence {_skill['name']}"
                                  if _ultra else f"🛠️ Compétence : {_skill['name']}")})

    # Compaction : résume les messages anciens (sortis de la fenêtre) et l'injecte dans le
    # prompt système → Marvin garde le fil des longues conversations sans tout réenvoyer.
    if _overflow:
        try:
            _summary = await _conversation_summary(conversation_id, _overflow, model=active_model)
            if _summary:
                system_prompt += "\n\n## Résumé du début de la conversation (compacté)\n" + _summary
        except Exception:
            pass

    _inject_learned_block(ollama_msgs, await _enrichments.learned_block())
    tools_payload = _assemble_tool_payload(
        await _enrichments.tools(),
        tools_spec=TOOLS_SPEC,
        explicit_tool_names=_explicit_tool_names,
        required_tool_names=_required_tool_names,
        skill=_skill,
        use_tools=use_tools,
    )

    # ── Boucle d'appel d'outils ───────────────────────────────────────────────
    assistant_text_accum = ""       # texte de la réponse courante
    tool_calls_for_db: list = []    # tool calls de l'étape courante
    tool_results_for_db: list = []  # résultats
    _runner_state = _RunnerState()
    _executed_tool_names = _runner_state.executed_tool_names

    async def _cortex_disagreement_escalation(critique_text: str | None, answer: str):
        return await _escalate_council_on_disagreement(
            critique_text,
            answer,
            cortex_plan=_cortex_plan,
            user_query=_user_query,
            council_tool=TOOLS_REGISTRY["ai_model_council"],
        )

    # NB : on NE force PAS num_ctx ici. Tester un num_ctx réduit (16K) a provoqué un RECHARGEMENT
    # du modèle à chaque message (Ollama indexe l'instance par (modèle, num_ctx) : le prewarm et
    # le « professeur » d'arrière-plan utilisent le défaut → conflit → thrash → 40s/message).
    # Le vrai gain (≈60s→16s) vient du professeur qui réutilise le modèle déjà chargé.
    # top_p resserre l'échantillonnage aux tokens les plus probables (complète la température
    # basse) : réduit le risque que le modèle « invente » un nom d'outil/paramètre plausible
    # mais faux plutôt que de rester sur ce qu'il connaît réellement (v2.106, anti-hallucination).
    _ollama_options = {"temperature": temperature, "top_p": 0.9}

    # Anti-« le modèle explique au lieu d'agir » : on ne le corrige qu'UNE fois.
    # Suivi de l'exécution et preuves pour l'auto-réparation des compétences.
    _run_trace = _runner_state.trace
    _run_calls = _runner_state.successful_calls
    _read_call_signatures: set[str] = set()
    _blocking_outcomes = _runner_state.blocking_outcomes
    _skill_outcomes = _SkillOutcomeRecorder()
    # v2.138 — compensation de la fiabilité composée : la littérature 2026 sur les agents LLM
    # documente qu'à 95% de fiabilité PAR appel, une chaîne de 8 outils ne réussit globalement
    # qu'à ~66% (les erreurs se composent). Pas de changement de comportement ici — juste une
    # trace visible (audit.jsonl) dès qu'un tour dépasse 8 appels, pour que ce signal soit
    # repérable lors d'un futur audit sans avoir à recompter manuellement les tool_start comme
    # fait à la main pour le diagnostic v2.136.

    # v2.142 — BUG RACINE trouvé en diagnostiquant pourquoi les instructions de projet
    # (ci-dessus) n'avaient AUCUN effet malgré une injection confirmée correcte dans
    # `system_prompt` : le champ top-level `"system"` de `/api/chat` Ollama Cloud est
    # SILENCIEUSEMENT IGNORÉ — testé en isolation sur 3 modèles (glm-5.2, deepseek-v4-
    # flash, qwen2.5:14b LOCAL) avec des instructions triviales ("réponds toujours en
    # anglais", "termine par ce tag exact") : 0/3 compliance via `"system": "..."`, 3/3
    # compliance en plaçant le MÊME contenu comme message `{"role":"system", ...}` dans
    # `messages[]`. Ce n'est PAS spécifique à un modèle ni au tool-calling (reproduit
    # avec et sans `tools`) — cela affecte potentiellement TOUTES les règles d'or de
    # `_build_system_prompt` depuis leur introduction, pas seulement cette fonctionnalité.
    # Corrigé en injectant `system_prompt` comme premier message plutôt que via le champ
    # dédié (gardé en plus, en pure redondance défensive — ne coûte rien s'il est ignoré).
    if not ollama_msgs or ollama_msgs[0].get("role") != "system":
        ollama_msgs.insert(0, {"role": "system", "content": system_prompt})
    else:
        ollama_msgs[0]["content"] = system_prompt

    async with _create_ollama_client(read_timeout=300.0) as _ollama_client:
      for step in range(_max_tool_steps):
        if not _runner_state.begin_step(step, _max_wall_seconds):
            break
        _model_step = _ModelStepResult()

        try:
            _request = _OllamaChatRequest(
                model=active_model,
                system_prompt=system_prompt,
                messages=ollama_msgs,
                tools=tools_payload,
                options=_ollama_options,
            )
            async for _event in _stream_model_step(
                client=_ollama_client,
                base_url=OLLAMA_URL,
                request=_request,
                stream_chat=_stream_ollama_chat,
                result=_model_step,
                suppress_text=bool(_blocking_outcomes),
            ):
                yield _sse(_event)
        except Exception as exc:
            yield _sse(_ollama_error_event(
                exc,
                model=active_model,
                base_url=OLLAMA_URL,
                read_timeout=300,
            ))
            return
        full_content = _model_step.content

        # ── Filet de sécurité : appels d'outils écrits en TEXTE/JSON ───────────
        # Si le modèle n'a pas émis d'appel natif mais a décrit des appels en JSON
        # dans le texte (fréquent avec les compétences pas-à-pas), on les récupère
        # pour AGIR réellement au lieu de seulement « parler ».
        _prepared_model_step = _prepare_model_step(
            content=full_content,
            native_tool_calls=_model_step.tool_calls,
            tools_payload=tools_payload,
            required_tool_names=_required_tool_names,
            executed_tool_names=_executed_tool_names,
            step=step,
            max_steps=_max_tool_steps,
            required_context=_RequiredToolContext(
                user_query=_user_query,
                workspace_normalized_query=_workspace_norm,
                workspace_mission_id=_workspace_mission_id,
                workspace_action=_workspace_action,
                messages=messages,
            ),
            salvage_text_tool_calls=_salvage_text_tool_calls,
            inject_required_tool_calls=_inject_required_tool_calls,
        )
        tool_calls_found = _prepared_model_step.tool_calls
        if _prepared_model_step.required_injected and full_content.strip():
            yield _sse({"type": "text", "text": "\n\n"})

        # v2.119 — protection mid-boucle : un outil sensible vient d'être demandé alors
        # qu'on est sur un modèle CLOUD → bascule en local AVANT que son résultat (contenu
        # d'email, sortie SSH…) ne parte vers le cloud au tour suivant. Le modèle cloud a pu
        # décider d'appeler cet outil sans que la détection initiale (mots-clés du message)
        # ne l'ait anticipé — dernier filet, pas le mécanisme principal.
        # v2.121 — désactivé en mode Ultra débridé (l'utilisateur a explicitement accepté
        # que ces données partent au cloud, y compris celles découvertes en cours de tour).
        if tool_calls_found and not _ultra and _is_cloud_model(active_model):
            if any(_is_sensitive_tool(tc.get("function", {}).get("name", "")) for tc in tool_calls_found):
                active_model = _local_fallback_model
                yield _sse({
                    "type":    "model_info",
                    "profile": profile_name,
                    "model":   active_model,
                    "label":   "🔒 Repli local (donnée sensible détectée)",
                })

        # ── Traiter les tool calls ─────────────────────────────────────────────
        if tool_calls_found:
            async for _event in _execute_tool_batch(
                tool_calls=tool_calls_found,
                assistant_content=full_content,
                ollama_messages=ollama_msgs,
                conversation_id=conversation_id,
                request_id=request_id,
                user_query=_user_query,
                active_model=active_model,
                permission_level=permission_level,
                explicit_tool_names=_explicit_tool_names,
                required_tool_names=_required_tool_names,
                command_text_only=_command_text_only,
                read_signatures=_read_call_signatures,
                runner_state=_runner_state,
                dangerous_tools=DANGEROUS_TOOLS,
                prepare_tool_call=_prepare_tool_call,
                inject_internal_context=_inject_internal_tool_context,
                dispatch_tool=_dispatch_tool,
                validate_tool_args=_validate_tool_args,
                execute_registered_tool=_execute_registered_tool,
                postprocess_tool_result=_postprocess_tool_result,
                critique_action=_critique_action,
                scan_document=_scan_dangerous_script_patterns,
                record_tool_observation=_record_tool_observation,
                record_long_chain=_record_long_chain,
                is_tooling_failure=_is_tooling_failure,
                compact_tool_result=_compact_tool_result,
                create_message=db.create_message,
            ):
                yield _sse(_event)

        elif (_skill and _skill.get("tools") and not _runner_state.nudged and use_tools and tools_payload
              and step < _max_tool_steps - 1):
            # ── Compétence active mais le modèle a EXPLIQUÉ au lieu d'AGIR ─────
            # (aucun appel natif, rien à récupérer dans le texte). On le corrige
            # UNE fois avec les noms d'outils EXACTS et on relance l'itération.
            _runner_state.nudged = True
            _avail = {s.get("function", {}).get("name") for s in tools_payload}
            _skill_tool_names = [t for t in _skill["tools"] if t in _avail]
            if full_content.strip():
                ollama_msgs.append({"role": "assistant", "content": full_content})
            ollama_msgs.append({"role": "user", "content": (
                "⛔ STOP. Tu as DÉCRIT les étapes au lieu d'AGIR. N'explique plus, ne réécris pas le plan. "
                "Exécute MAINTENANT, via un VRAI appel d'outil (pas de texte, pas de bloc JSON), "
                "l'outil le plus pertinent pour la 1ʳᵉ étape — un seul. "
                + (f"Utilise EXACTEMENT l'un de ces noms d'outils : {', '.join(_skill_tool_names)}."
                   if _skill_tool_names else "Utilise l'un des outils fournis."))})
            yield _sse({"type": "text", "text": "\n\n"})
            continue

        else:
            # ── Réponse finale — pas de tool calls ────────────────────────────
            if _blocking_outcomes:
                details = []
                for failed_tool, receipt in _blocking_outcomes.items():
                    failed_steps = receipt.get("failed_steps") or receipt.get("test_report", {}).get("failed_steps") or []
                    reason = receipt.get("error") or receipt.get("message") or "gate de qualité non validé"
                    suffix = f" Étapes en échec : {', '.join(map(str, failed_steps))}." if failed_steps else ""
                    details.append(f"- `{failed_tool}` : {reason}.{suffix}")
                full_content = (
                    "## Validation non obtenue\n\n"
                    "Je ne peux pas annoncer que le code ou les tests ont réussi : le dernier reçu Forge est négatif.\n\n"
                    + "\n".join(details)
                    + "\n\nLe livrable reste refusé tant qu'une correction suivie d'un nouveau reçu `production_ready=true` n'a pas été observée."
                )
                yield _sse({"type": "text", "text": full_content})
            _review_mode = _cortex_plan["resolved"]["review"]
            _force_review = _review_mode in {"verify", "council_if_disagreement"}
            _finalized = await _finalize_answer(
                user_query=_user_query,
                content=full_content,
                active_model=active_model,
                force_review=_force_review,
                script_scanner=_scan_dangerous_script_patterns,
                critique_pass=_run_critique_pass,
                council_escalation=_cortex_disagreement_escalation,
            )
            full_content = _finalized.content
            for _event in _finalized.events:
                yield _sse(_event)
            _critique = _finalized.critique
            if _finalized.council_executed:
                _executed_tool_names.add("ai_model_council")

            db.create_message(conversation_id, "assistant", full_content)

            # v2.170 — le titrage se fait désormais immédiatement à l'envoi du message
            # utilisateur (voir plus haut, _autotitle_from_text) — bloc post-hoc retiré,
            # devenu redondant et surtout jamais atteint si le tour est interrompu avant.

            _schedule_exchange_learning(
                user_query=_user_query,
                final_content=full_content,
                active_model=active_model,
                background_tasks=_BG_LEARN_TASKS,
                get_setting=db.get_setting,
            )

            # Auto-réparation des compétences (enregistre l'issue + auto-upgrade si échec).
            _up_msg = _skill_outcomes.finalize(
                skill=_skill,
                runner_state=_runner_state,
                user_query=_user_query,
                final_content=full_content,
                tools_spec=TOOLS_SPEC,
                background_tasks=_BG_LEARN_TASKS,
                encode_sse=_sse,
            )
            if _up_msg:
                yield _up_msg

            try:
                _cortex.record_recipe_outcome(
                    _cortex_plan["requested"].get("recipe_id"), _runner_state.succeeded, _executed_tool_names
                )
            except Exception:
                pass

            yield _sse({
                "type": "cortex_provenance",
                "provenance": _cortex.provenance(
                    _cortex_plan, active_model, _executed_tool_names,
                    critique=bool(_critique), answer=full_content, conversation_id=conversation_id,
                    budget_usage=_runner_state.budget_usage("criteria_satisfied"),
                ),
            })
            yield _sse({"type": "done"})
            return

    _budget_stop_reason = _runner_state.finish_reason()
    # Budget d'étapes ou de temps atteint — v2.126 : jusqu'ici on terminait la boucle
    # SANS RIEN RENVOYER, ni texte ni message sauvegardé — l'utilisateur voyait le flux
    # s'arrêter net après le dernier tool_end, sans aucune réponse. C'est exactement le
    # symptôme rapporté (« Marvin continue de réfléchir sans rien faire ») : reproduit en
    # réel avec une requête de recherche web qui a enchaîné 11 tool_start sans jamais
    # produire de texte. On force maintenant UN dernier appel, SANS outils, pour obtenir
    # une synthèse de ce qui a déjà été trouvé plutôt qu'un silence total.
    ollama_msgs.append({"role": "user", "content": (
        f"⛔ Tu as atteint le budget ({_budget_stop_reason}) pour ce tour. Tu ne peux PLUS utiliser "
        "aucun outil. Réponds MAINTENANT, en français, avec une synthèse aussi complète que "
        "possible de ce que tu as déjà trouvé pour répondre à la demande initiale de "
        "l'utilisateur. Si des informations manquent encore, dis-le clairement plutôt que de "
        "rester silencieux."
    )})
    full_content = ""
    try:
        async with _create_ollama_client(read_timeout=120.0) as _final_client:
            _final_request = _OllamaChatRequest(
                model=active_model,
                system_prompt=system_prompt,
                messages=ollama_msgs,
                tools=None,
                options=_ollama_options,
            )
            async for event in _stream_ollama_chat(_final_client, OLLAMA_URL, _final_request):
                if event.kind == "text":
                    full_content += event.text
                    yield _sse({"type": "text", "text": event.text})
    except Exception:
        pass

    if not full_content.strip():
        full_content = ("Je n'ai pas réussi à conclure cette recherche dans le nombre d'étapes "
                         "autorisées. Peux-tu préciser ta demande ou me demander de continuer ?")
        yield _sse({"type": "text", "text": full_content})

    _review_mode = _cortex_plan["resolved"]["review"]
    _force_review = _review_mode in {"verify", "council_if_disagreement"}
    _finalized = await _finalize_answer(
        user_query=_user_query,
        content=full_content,
        active_model=active_model,
        force_review=_force_review,
        script_scanner=_scan_dangerous_script_patterns,
        critique_pass=_run_critique_pass,
        council_escalation=_cortex_disagreement_escalation,
    )
    full_content = _finalized.content
    for _event in _finalized.events:
        yield _sse(_event)
    _critique = _finalized.critique
    if _finalized.council_executed:
        _executed_tool_names.add("ai_model_council")

    db.create_message(conversation_id, "assistant", full_content)

    # Enregistre tout de même l'issue de la compétence (souvent un signe de faiblesse).
    _up_msg = _skill_outcomes.finalize(
        skill=_skill,
        runner_state=_runner_state,
        user_query=_user_query,
        final_content=full_content,
        tools_spec=TOOLS_SPEC,
        background_tasks=_BG_LEARN_TASKS,
        encode_sse=_sse,
    )
    if _up_msg:
        yield _up_msg
    try:
        _cortex.record_recipe_outcome(
            _cortex_plan["requested"].get("recipe_id"), _runner_state.succeeded, _executed_tool_names
        )
    except Exception:
        pass
    yield _sse({
        "type": "cortex_provenance",
        "provenance": _cortex.provenance(
            _cortex_plan, active_model, _executed_tool_names,
            critique=bool(_critique), answer=full_content, conversation_id=conversation_id,
            budget_usage=_runner_state.budget_usage(_budget_stop_reason),
        ),
    })
    yield _sse({"type": "done"})
