"""
SecretaryAI Backend — Runner agentique de streaming.
Orchestre Ollama via l'adaptateur de transport, gère la boucle d'appel d'outils
et produit les événements SSE du frontend.
"""
import asyncio
import time
from typing import AsyncIterator

import cloud_routing as _cr
import cortex as _cortex
import database as db
import memory_mesh
import tool_runtime
from agent_orchestration import (
    dispatch_agent as _dispatch_agent_runtime,
    request_mode as _request_orchestrator_mode,
)
from intent_guard import skill_match_text
from agent_prompt import build_system_prompt as _build_system_prompt
from agent_protocol import encode_sse as _sse, to_ollama_messages as _to_ollama_messages
from agent_routing import (
    SENSITIVE_TOOL_PREFIXES as _SENSITIVE_TOOL_PREFIXES,
    detect_profile as _detect_profile,
    get_cloud_config as _get_cloud_config,
    is_cloud_model as _is_cloud_model,
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
    record_empty_model_response as _record_empty_model_response,
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
from agent_turn_completion import complete_turn as _complete_turn
from agent_loop_policy import (
    build_action_execution_nudge as _build_action_execution_nudge,
    build_computer_action_nudge as _build_computer_action_nudge,
    build_empty_response_nudge as _build_empty_response_nudge,
    build_native_budget_nudge as _build_native_budget_nudge,
    build_skill_nudge as _build_skill_nudge,
    promises_unexecuted_action as _promises_unexecuted_action,
    requires_computer_action_nudge as _requires_computer_action_nudge,
    render_blocking_outcomes as _render_blocking_outcomes,
    render_latest_web_result as _render_latest_web_result,
    retryable_cloud_model_error as _retryable_cloud_model_error,
    native_tool_call_limit as _native_tool_call_limit,
    should_suppress_model_text as _should_suppress_model_text,
    skill_requires_nudge as _skill_requires_nudge,
    sensitive_tool_model_switch as _sensitive_tool_model_switch,
)
from agent_budget_completion import synthesize_budget_answer as _synthesize_budget_answer
from agent_transport import (
    OllamaChatRequest as _OllamaChatRequest,
    create_client as _create_ollama_client,
    error_event as _ollama_error_event,
    public_error_reason as _ollama_public_error_reason,
    stream_chat as _stream_ollama_chat,
)
from agent_tool_selection import filter_relevant_tools as _filter_relevant_tools
from capability_catalog import CapabilityCatalog as _CapabilityCatalog
from native_agent_prompt import build_native_system_prompt as _build_native_system_prompt
from config import (
    OLLAMA_URL, MAX_CONTEXT_MESSAGES,
    DEFAULT_PERMISSION_LEVEL, DANGEROUS_TOOLS,
    MODEL_PROFILES, AUTO_MODE_FALLBACKS,
)
from tools import TOOLS_REGISTRY, TOOLS_SPEC

_validate_tool_args = validator_for(TOOLS_SPEC)

# Conserve les références des tâches d'apprentissage en arrière-plan (anti-GC).
_BG_LEARN_TASKS: set = set()

# ── Agent de streaming principal ──────────────────────────────────────────────

async def _run_deterministic_agent(
    messages: list[dict],
    conversation_id: str | None,
    model: str | None,
    cortex_contract: dict | None = None,
    request_id: str | None = None,
    *,
    native_decision_mode: bool = False,
    internal_continuation: bool = False,
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
        persist_user_message=not internal_continuation,
    )
    conversation_id = _prepared_turn.conversation_id
    _user_query = _prepared_turn.user_query
    for _turn_event in _prepared_turn.events:
        yield _sse(_turn_event)
    _turn_plan = _compile_turn_plan(
        messages,
        _user_query,
        cortex_contract,
        llm_native=native_decision_mode,
    )
    _explicit_tool_names = _turn_plan.explicit_tool_names
    _command_text_only = _turn_plan.command_text_only
    _tool_suppression = _turn_plan.tool_suppression
    _required_tool_names = _turn_plan.required_tool_names
    _workspace_norm = _turn_plan.workspace_norm
    _workspace_mission_id = _turn_plan.workspace_mission_id
    _workspace_action = _turn_plan.workspace_action
    _cortex_plan = _turn_plan.cortex_plan
    _max_tool_steps = _turn_plan.max_tool_steps
    _max_wall_seconds = _turn_plan.max_wall_seconds
    _contextual_web_query = _turn_plan.contextual_web_query
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
        build_system_prompt=(
            _build_native_system_prompt
            if native_decision_mode
            else _build_system_prompt
        ),
        # Le contrat Cortex reste utilisé pour les budgets et la confidentialité,
        # mais son ancien mode métier « advise/act » ne doit pas reprendre le contrôle
        # de la décision d'outil dans l'orchestrateur natif.
        cortex_prompt_block=(
            (lambda _plan: "")
            if native_decision_mode
            else _cortex.prompt_block
        ),
        get_real_paths=(
            None if native_decision_mode else execute_pc_get_real_paths
        ),
        filter_memories=memory_mesh.filter_active,
        contextual_web_query=_contextual_web_query,
        include_document_identity=not native_decision_mode,
    )
    _overflow = _base_context.overflow
    ollama_msgs = _base_context.ollama_messages
    system_prompt = _base_context.system_prompt
    permission_level = _base_context.permission_level
    use_tools = _base_context.use_tools
    if native_decision_mode and not _tool_suppression:
        # Le mode historique « advise » désactivait entièrement les schémas d'outils.
        # Dans la boucle native, le LLM doit au minimum pouvoir découvrir les
        # capacités; le gateway reste seul autoritaire pour leur exécution.
        use_tools = bool(MODEL_PROFILES.get(profile_name, {}).get("tools", True))

    # Connaissances apprises : rappel SÉMANTIQUE → injecté EN TÊTE (priorité absolue,
    # sinon noyé dans le long prompt de capacités et ignoré par le modèle).
    # Rappel mémoire (embed) + filtrage des outils (embed) = 2 opérations INDÉPENDANTES.
    # On les lance EN PARALLÈLE (gain de latence, résultat identique) et on construit le
    # prompt système pendant ce temps.
    async def _native_bootstrap_tools(
        _messages: list[dict],
        _profile_name: str,
    ) -> list[dict]:
        return [
            specification
            for specification in TOOLS_SPEC
            if specification.get("function", {}).get("name") == "tool_search"
        ]

    async def _native_no_skill(_text: str) -> None:
        return None

    async def _native_no_recall(_text: str) -> list[dict]:
        # La boucle native récupère les connaissances à la demande via des outils.
        # Un rappel implicite ne doit pas contaminer sa décision d'agir.
        return []

    _enrichments = _start_enrichments(
        messages=messages,
        user_query=_user_query,
        profile_name=profile_name,
        use_tools=use_tools,
        tool_suppression=_tool_suppression,
        skill_matcher_text=skill_match_text,
        filter_tools=(
            _native_bootstrap_tools
            if native_decision_mode
            else _filter_relevant_tools
        ),
        match_skill=(
            _native_no_skill if native_decision_mode else None
        ),
        recall=(
            _native_no_recall if native_decision_mode else None
        ),
        recall_block=(
            (lambda _items: "") if native_decision_mode else None
        ),
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
            _local_fallback_model = _agent_local
            yield _sse(_model_config.event(
                profile_name="agent",
                active_model=active_model,
                label=(
                    f"☁️ Cloud strict · compétence {_skill['name']}"
                    if _ultra
                    else f"🛠️ Compétence : {_skill['name']}"
                ),
            ))

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
    if native_decision_mode:
        yield _sse({
            "type": "capability_context",
            "enabled": bool(use_tools),
            "count": len(tools_payload),
            "system_chars": len(system_prompt),
            "message_roles": [
                str(message.get("role") or "")
                for message in ollama_msgs
            ],
            "message_chars": [
                len(str(message.get("content") or ""))
                for message in ollama_msgs
            ],
            "names": [
                str(spec.get("function", {}).get("name") or "")
                for spec in tools_payload
            ],
        })

    # ── Boucle d'appel d'outils ───────────────────────────────────────────────
    _runner_state = _RunnerState()
    _executed_tool_names = _runner_state.executed_tool_names

    async def _run_council_tool(arguments: dict):
        outcome = await tool_runtime.execute(
            "ai_model_council",
            arguments,
            source="agent_cortex",
            conversation_id=conversation_id,
            request_id=request_id,
        )
        return outcome.result

    async def _execute_agent_tool(
        tool_name: str,
        arguments: dict,
        tool_conversation_id: str,
        tool_request_id: str | None,
    ):
        """Fait traverser tous les appels du chat par le gateway d'effets commun."""
        outcome = await tool_runtime.execute(
            tool_name,
            arguments,
            source="agent_chat",
            conversation_id=tool_conversation_id,
            request_id=tool_request_id,
            permission_level=permission_level,
        )
        return outcome.result

    async def _cortex_disagreement_escalation(critique_text: str | None, answer: str):
        return await _escalate_council_on_disagreement(
            critique_text,
            answer,
            cortex_plan=_cortex_plan,
            user_query=_user_query,
            council_tool=_run_council_tool,
        )

    async def _finish_turn(
        content: str,
        stop_reason: str,
        *,
        learn: bool,
    ):
        review_mode = _cortex_plan["resolved"]["review"]
        return await _complete_turn(
            user_query=_user_query,
            content=content,
            active_model=active_model,
            conversation_id=conversation_id,
            cortex_plan=_cortex_plan,
            runner_state=_runner_state,
            executed_tool_names=_executed_tool_names,
            stop_reason=stop_reason,
            force_review=review_mode in {"verify", "council_if_disagreement"},
            skill=_skill,
            skill_outcomes=_skill_outcomes,
            tools_spec=TOOLS_SPEC,
            background_tasks=_BG_LEARN_TASKS,
            schedule_learning=learn,
            finalize_answer=_finalize_answer,
            script_scanner=_scan_dangerous_script_patterns,
            critique_pass=_run_critique_pass,
            council_escalation=_cortex_disagreement_escalation,
            create_message=db.create_message,
            schedule_exchange_learning=_schedule_exchange_learning,
            get_setting=db.get_setting,
            record_recipe_outcome=_cortex.record_recipe_outcome,
            build_provenance=_cortex.provenance,
            encode_sse=_sse,
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

    _failed_cloud_models: set[str] = set()
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
                suppress_text=_should_suppress_model_text(
                    has_blocking_outcomes=bool(_blocking_outcomes),
                    required_tool_names=_required_tool_names,
                    executed_tool_names=_executed_tool_names,
                ),
            ):
                yield _sse(_event)
        except Exception as exc:
            if (
                _is_cloud_model(active_model)
                and not _model_step.content
                and not _model_step.tool_calls
                and _retryable_cloud_model_error(exc)
                and len(_failed_cloud_models) < 2
                and step < _max_tool_steps - 1
            ):
                _failed_cloud_models.add(active_model)
                _fallback_need = (
                    _cr.detect_task(_user_query)
                    or {
                        "analysis": "reasoning",
                        "agent": "agentic",
                        "vision": "vision",
                    }.get(profile_name, "general")
                )
                try:
                    import model_market as _model_market

                    _model_market.record_observation(
                        active_model,
                        _fallback_need,
                        False,
                        int(
                            (time.monotonic() - _runner_state.started_at)
                            * 1000
                        ),
                        phase="agent_transport",
                        error_type=type(exc).__name__,
                    )
                except Exception:
                    pass
                _alternate_cloud = _cr.pick_best_cloud_model(
                    _fallback_need,
                    exclude=frozenset(_failed_cloud_models),
                )
                if _alternate_cloud and _alternate_cloud != active_model:
                    _public_reason = _ollama_public_error_reason(exc)
                    active_model = _alternate_cloud
                    yield _sse({
                        "type": "model_info",
                        "profile": profile_name,
                        "model": active_model,
                        "label": f"Repli Cloud · {active_model}",
                        "provider": "ollama_cloud",
                        "privacyMode": "ultra_cloud" if _ultra else "standard",
                        "privacyPreset": _cr.get_privacy_preset(),
                        "cloudOnly": _ultra,
                        "sensitive": _model_config.sensitive,
                        "switchReason": (
                            _public_reason[0]
                            if _public_reason
                            else "cloud_model_unavailable"
                        ),
                        "switchMessage": (
                            _public_reason[1]
                            if _public_reason
                            else "Le modèle Cloud initial est temporairement indisponible."
                        ),
                    })
                    continue
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
                successful_results=_runner_state.successful_results,
            ),
            salvage_text_tool_calls=(
                (lambda _content, _allowed: [])
                if native_decision_mode
                else _salvage_text_tool_calls
            ),
            inject_required_tool_calls=_inject_required_tool_calls,
        )
        tool_calls_found = _prepared_model_step.tool_calls
        if _is_cloud_model(active_model) and (
            full_content.strip() or tool_calls_found
        ):
            # Toute réponse Cloud exploitable alimente le marché. Sans les
            # réponses textuelles positives, les statistiques générales ne
            # contenaient que des pannes et favorisaient des modèles non éprouvés.
            try:
                import model_market as _model_market

                _observed_need = (
                    "agentic"
                    if tool_calls_found
                    else (
                        _cr.detect_task(_user_query)
                        or {
                            "analysis": "reasoning",
                            "agent": "agentic",
                            "vision": "vision",
                        }.get(profile_name, "general")
                    )
                )
                if not tool_calls_found:
                    _model_market.record_observation(
                        active_model,
                        _observed_need,
                        True,
                        int((time.monotonic() - _runner_state.started_at) * 1000),
                        phase="agent_model_step",
                    )
            except Exception:
                pass
        # v2.119 — protection mid-boucle : un outil sensible vient d'être demandé alors
        # qu'on est sur un modèle CLOUD → bascule en local AVANT que son résultat (contenu
        # d'email, sortie SSH…) ne parte vers le cloud au tour suivant. Le modèle cloud a pu
        # décider d'appeler cet outil sans que la détection initiale (mots-clés du message)
        # ne l'ait anticipé — dernier filet, pas le mécanisme principal.
        # v2.121 — désactivé en mode Ultra débridé (l'utilisateur a explicitement accepté
        # que ces données partent au cloud, y compris celles découvertes en cours de tour).
        _decision_model = active_model
        _model_switch = _sensitive_tool_model_switch(
            tool_calls=tool_calls_found,
            active_model=active_model,
            profile_name=profile_name,
            local_fallback_model=_local_fallback_model,
            ultra_cloud_only=_ultra,
            is_cloud_model=_is_cloud_model,
            is_sensitive_tool=_is_sensitive_tool,
        )
        if _model_switch:
            active_model = _model_switch.model
            yield _sse(_model_switch.event)

        # ── Traiter les tool calls ─────────────────────────────────────────────
        if tool_calls_found:
            _successful_call_count_before = len(_runner_state.successful_calls)
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
                execute_registered_tool=_execute_agent_tool,
                postprocess_tool_result=_postprocess_tool_result,
                critique_action=_critique_action,
                scan_document=_scan_dangerous_script_patterns,
                record_tool_observation=_record_tool_observation,
                record_long_chain=_record_long_chain,
                is_tooling_failure=_is_tooling_failure,
                compact_tool_result=_compact_tool_result,
                create_message=db.create_message,
                tool_argument_overrides=(
                    {
                        "web_research": {"query": _contextual_web_query},
                        "web_deep_research": {"query": _contextual_web_query},
                    }
                    if _contextual_web_query
                    else None
                ),
                tool_timeout_seconds=max(
                    1.0,
                    _max_wall_seconds
                    - (time.monotonic() - _runner_state.started_at),
                ),
            ):
                yield _sse(_event)
            if (
                _is_cloud_model(_decision_model)
                and len(_runner_state.successful_calls)
                > _successful_call_count_before
            ):
                try:
                    import model_market as _model_market

                    _model_market.record_observation(
                        _decision_model,
                        "agentic",
                        True,
                        int((time.monotonic() - _runner_state.started_at) * 1000),
                        phase="tool_execution",
                    )
                    _cr.record_model_capability(
                        _decision_model,
                        "agentic",
                        True,
                    )
                except Exception:
                    pass
            if native_decision_mode:
                # `tool_search` reste consultatif. Après son observation, seuls les
                # schémas exacts des candidats sont ajoutés pour le prochain tour.
                latest_discovery = next(
                    (
                        item
                        for item in reversed(_runner_state.successful_results)
                        if item.get("tool") == "tool_search"
                        and item.get("candidates")
                    ),
                    None,
                )
                if latest_discovery:
                    catalog = _CapabilityCatalog(TOOLS_SPEC)
                    names = [
                        str(item.get("name") or "")
                        for item in latest_discovery["candidates"]
                        if isinstance(item, dict)
                    ]
                    present = {
                        str(item.get("function", {}).get("name") or "")
                        for item in tools_payload
                    }
                    for specification in catalog.exact_specifications(names):
                        name = str(
                            specification.get("function", {}).get("name") or ""
                        )
                        if name and name not in present:
                            tools_payload.append(specification)
                            present.add(name)
                newly_exhausted = {
                    str(spec.get("function", {}).get("name") or "")
                    for spec in tools_payload
                    if (
                        str(spec.get("function", {}).get("name") or "")
                        not in _runner_state.exhausted_tool_budgets
                        and _runner_state.attempted_call_count(
                            str(spec.get("function", {}).get("name") or "")
                        )
                        >= _native_tool_call_limit(
                            str(spec.get("function", {}).get("name") or "")
                        )
                    )
                }
                if newly_exhausted:
                    _runner_state.exhausted_tool_budgets.update(newly_exhausted)
                    tools_payload[:] = [
                        spec
                        for spec in tools_payload
                        if str(spec.get("function", {}).get("name") or "")
                        not in newly_exhausted
                    ]
                    ollama_msgs.append(
                        _build_native_budget_nudge(newly_exhausted)
                    )
                    yield _sse({
                        "type": "capability_budget",
                        "exhausted": sorted(newly_exhausted),
                        "remaining": len(tools_payload),
                    })

        elif (
            not full_content.strip()
            and not _runner_state.empty_response_nudged
            and step < _max_tool_steps - 1
        ):
            # Une réponse vide n'est jamais un succès. On accorde une seule relance
            # déterministe, puis le chemin terminal sans outils produira une réponse
            # explicite si le modèle reste silencieux.
            _runner_state.empty_response_nudged = True
            _remaining_required = _required_tool_names - _executed_tool_names
            if _is_cloud_model(active_model):
                _empty_need = (
                    "agentic"
                    if native_decision_mode and tools_payload
                    else (
                        _cr.detect_task(_user_query)
                        or {
                            "analysis": "reasoning",
                            "agent": "agentic",
                            "vision": "vision",
                        }.get(profile_name, "general")
                    )
                )
                try:
                    import model_market as _model_market

                    _model_market.record_observation(
                        active_model,
                        _empty_need,
                        False,
                        int(
                            (time.monotonic() - _runner_state.started_at)
                            * 1000
                        ),
                        phase="empty_agent_response",
                        error_type="EmptyModelResponse",
                    )
                except Exception:
                    pass
                _alternate_cloud = _cr.pick_best_cloud_model(
                    _empty_need,
                    exclude=frozenset({active_model}),
                )
                if _alternate_cloud and _alternate_cloud != active_model:
                    active_model = _alternate_cloud
                    yield _sse({
                        "type": "model_info",
                        "profile": profile_name,
                        "model": active_model,
                        "label": f"Repli réponse vide · {active_model}",
                        "provider": "ollama_cloud",
                        "privacyMode": "ultra_cloud" if _ultra else "standard",
                        "privacyPreset": _cr.get_privacy_preset(),
                        "cloudOnly": _ultra,
                        "sensitive": _model_config.sensitive,
                        "switchReason": "empty_model_response",
                    })
            ollama_msgs.append(_build_empty_response_nudge(
                required_tool_names=_remaining_required,
            ))
            continue

        elif not full_content.strip():
            _runner_state.stop_reason = "empty_model_response"
            if _is_cloud_model(active_model):
                _terminal_empty_need = (
                    "agentic"
                    if native_decision_mode and tools_payload
                    else (
                        _cr.detect_task(_user_query)
                        or {
                            "analysis": "reasoning",
                            "agent": "agentic",
                            "vision": "vision",
                        }.get(profile_name, "general")
                    )
                )
                try:
                    import model_market as _model_market

                    _model_market.record_observation(
                        active_model,
                        _terminal_empty_need,
                        False,
                        int(
                            (time.monotonic() - _runner_state.started_at)
                            * 1000
                        ),
                        phase="empty_agent_response_terminal",
                        error_type="EmptyModelResponse",
                    )
                except Exception:
                    pass
            _record_empty_model_response(
                conversation_id=conversation_id,
                model=active_model,
                required_tool_count=len(_required_tool_names),
                executed_tool_count=len(_executed_tool_names),
            )
            break

        elif (
            _requires_computer_action_nudge(
                _user_query,
                executed_tool_names=_executed_tool_names,
                available_tool_names={
                    str(spec.get("function", {}).get("name") or "")
                    for spec in tools_payload
                    if spec.get("function", {}).get("name")
                },
                successful_calls=_runner_state.successful_calls,
                recent_user_queries=[
                    str(message.get("content") or "")
                    for message in messages
                    if message.get("role") == "user"
                ],
            )
            and not _runner_state.nudged
            and step < _max_tool_steps - 1
        ):
            _runner_state.nudged = True
            ollama_msgs.append({"role": "assistant", "content": full_content})
            ollama_msgs.extend(_build_computer_action_nudge())
            yield _sse({"type": "text", "text": "\n\n"})
            continue

        elif (
            _promises_unexecuted_action(
                full_content,
                executed_tool_names=_executed_tool_names,
                tools_available=bool(tools_payload),
            )
            and not _runner_state.nudged
            and step < _max_tool_steps - 1
        ):
            _runner_state.nudged = True
            _available_names = {
                str(spec.get("function", {}).get("name") or "")
                for spec in tools_payload
                if spec.get("function", {}).get("name")
            }
            ollama_msgs.append({"role": "assistant", "content": full_content})
            ollama_msgs.extend(_build_action_execution_nudge(
                available_tool_names=_available_names,
            ))
            yield _sse({"type": "text", "text": "\n\n"})
            continue

        elif (_skill_requires_nudge(
                  skill=_skill,
                  tools_payload=tools_payload,
                  executed_tool_names=_executed_tool_names,
              ) and not _runner_state.nudged and use_tools and tools_payload
              and step < _max_tool_steps - 1):
            # ── Compétence active mais le modèle a EXPLIQUÉ au lieu d'AGIR ─────
            # (aucun appel natif, rien à récupérer dans le texte). On le corrige
            # UNE fois avec les noms d'outils EXACTS et on relance l'itération.
            _runner_state.nudged = True
            ollama_msgs.extend(_build_skill_nudge(
                skill=_skill,
                tools_payload=tools_payload,
                full_content=full_content,
            ))
            yield _sse({"type": "text", "text": "\n\n"})
            continue

        else:
            # ── Réponse finale — pas de tool calls ────────────────────────────
            if (
                _runner_state.nudged
                and _requires_computer_action_nudge(
                    _user_query,
                    executed_tool_names=_executed_tool_names,
                    available_tool_names={
                        str(spec.get("function", {}).get("name") or "")
                        for spec in tools_payload
                        if spec.get("function", {}).get("name")
                    },
                    successful_calls=_runner_state.successful_calls,
                    recent_user_queries=[
                        str(message.get("content") or "")
                        for message in messages
                        if message.get("role") == "user"
                    ],
                )
                and _is_cloud_model(active_model)
            ):
                try:
                    import model_market as _model_market

                    _model_market.record_observation(
                        active_model,
                        "agentic",
                        False,
                        int((time.monotonic() - _runner_state.started_at) * 1000),
                        phase="computer_action_unfulfilled",
                        error_type="MissionNotExecuted",
                    )
                except Exception:
                    pass
            if _promises_unexecuted_action(
                full_content,
                executed_tool_names=_executed_tool_names,
                tools_available=bool(tools_payload),
            ):
                _web_receipt_answer = _render_latest_web_result(
                    _runner_state.successful_results
                )
                if _web_receipt_answer:
                    full_content = _web_receipt_answer
            _blocking_answer = _render_blocking_outcomes(_blocking_outcomes)
            if _blocking_answer:
                full_content = _blocking_answer
                yield _sse({"type": "text", "text": full_content})
            _completion = await _finish_turn(
                full_content,
                "criteria_satisfied",
                learn=True,
            )
            for _event in _completion.events:
                yield _event
            return

    _budget_stop_reason = _runner_state.finish_reason()
    # Budget d'étapes ou de temps atteint — v2.126 : jusqu'ici on terminait la boucle
    # SANS RIEN RENVOYER, ni texte ni message sauvegardé — l'utilisateur voyait le flux
    # s'arrêter net après le dernier tool_end, sans aucune réponse. C'est exactement le
    # symptôme rapporté (« Marvin continue de réfléchir sans rien faire ») : reproduit en
    # réel avec une requête de recherche web qui a enchaîné 11 tool_start sans jamais
    # produire de texte. On force maintenant UN dernier appel, SANS outils, pour obtenir
    # une synthèse de ce qui a déjà été trouvé plutôt qu'un silence total.
    full_content = ""
    async for _event in _synthesize_budget_answer(
        stop_reason=_budget_stop_reason,
        active_model=active_model,
        system_prompt=system_prompt,
        ollama_messages=ollama_msgs,
        options=_ollama_options,
        base_url=OLLAMA_URL,
        request_factory=_OllamaChatRequest,
        client_factory=_create_ollama_client,
        stream_chat=_stream_ollama_chat,
    ):
        if _event["type"] == "_budget_answer":
            full_content = _event["content"]
        else:
            yield _sse(_event)

    _completion = await _finish_turn(
        full_content,
        _budget_stop_reason,
        learn=False,
    )
    for _event in _completion.events:
        yield _event


async def run_agent(
    messages: list[dict],
    conversation_id: str | None,
    model: str | None,
    cortex_contract: dict | None = None,
    request_id: str | None = None,
    internal_continuation: bool = False,
) -> AsyncIterator[str]:
    """Point d'entrée stable, commutable sans modifier les routes HTTP."""

    def deterministic_factory() -> AsyncIterator[str]:
        return _run_deterministic_agent(
            messages,
            conversation_id,
            model,
            cortex_contract,
            request_id,
            internal_continuation=internal_continuation,
        )

    def native_factory() -> AsyncIterator[str]:
        return _run_deterministic_agent(
            messages,
            conversation_id,
            model,
            cortex_contract,
            request_id,
            native_decision_mode=True,
            internal_continuation=internal_continuation,
        )

    async for event in _dispatch_agent_runtime(
        deterministic_factory=deterministic_factory,
        native_factory=native_factory,
        encode_event=_sse,
        requested=_request_orchestrator_mode(
            ultra_unrestricted=_is_ultra_unrestricted(),
        ),
    ):
        yield event
