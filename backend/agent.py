"""
SecretaryAI Backend — Runner agentique de streaming.
Orchestre Ollama via l'adaptateur de transport, gère la boucle d'appel d'outils
et produit les événements SSE du frontend.
"""
import asyncio
import json
import re
import time
import uuid
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
    ToolObservation as _ToolObservation,
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
from agent_transport import (
    OllamaChatRequest as _OllamaChatRequest,
    create_client as _create_ollama_client,
    error_event as _ollama_error_event,
    stream_chat as _stream_ollama_chat,
)
from agent_tool_selection import filter_relevant_tools as _filter_relevant_tools
from config import (
    OLLAMA_URL, MAX_CONTEXT_MESSAGES,
    PERMISSION_SECURE, PERMISSION_EXPERT, DEFAULT_PERMISSION_LEVEL,
    SECURE_BLOCKED_TOOLS, DANGEROUS_TOOLS,
    MODEL_PROFILES,
)
from tools import TOOLS_REGISTRY, TOOLS_SPEC

_validate_tool_args = validator_for(TOOLS_SPEC)

# Conserve les références des tâches d'apprentissage en arrière-plan (anti-GC).
_BG_LEARN_TASKS: set = set()

# ── Prompt système ────────────────────────────────────────────────────────────



# ── Conversion messages frontend → Ollama ─────────────────────────────────────

# v2.138 — validation légère des arguments AVANT exécution (1ʳᵉ des 3 couches recommandées pour
# le tool-calling agentique : validation → retry ciblé → decoding contraint — la 2ᵉ existe déjà
# via le garde de sécurité + le repli de modèle, celle-ci comblait le seul vrai trou). Volontai-
# rement CONSERVATRICE : ne vérifie que la PRÉSENCE des paramètres obligatoires (déclarés dans
# TOOLS_SPEC) — pas de coercition de type stricte, qui casserait des appels qui fonctionnent
# déjà (beaucoup d'outils acceptent un nombre envoyé en chaîne, etc.). Objectif : intercepter
# le cas concret déjà rencontré en audit (paramètre requis totalement absent → l'outil part sur
# une KeyError/valeur par défaut fausse) avant même l'appel, pas remplacer les validations
# internes déjà présentes dans chaque `execute_*`.
# v2.131 — filet de sécurité DÉTERMINISTE sur les réponses techniques (scripts). La règle
# d'or #11 (ne pas toucher à l'authentification root d'une base de données) reste violée
# par le modèle cloud dans ~2 générations sur 3 malgré une interdiction explicite et sans
# exception dans le prompt système, testé en réel — un rappel textuel, même explicite, ne
# garantit JAMAIS un comportement 100% fiable sur un LLM probabiliste. Plutôt que de
# continuer à durcir un texte qui a déjà atteint son plafond d'efficacité, on ajoute un
# SCAN a posteriori du texte final : motifs regex connus et sans ambiguïté (contrairement
# à `security.py::screen_command`, ceci ne bloque RIEN — la réponse contient un script à
# LIRE, pas une commande à EXÉCUTER — mais rend le risque visible et impossible à manquer).
# v2.141 — Passe de critique par un 2ᵉ modèle (demandé explicitement : « je pense que
# quand une demande est faite le llm cloud répond mais doit aussi passer après réponse
# par une revue critique d'un autre llm avant d'envoyer la réponse »). Complète le
# scanner déterministe ci-dessus (regex, ne peut voir que des motifs connus à l'avance)
# avec un vrai jugement de modèle — principe Mixture-of-Agents (un 2ᵉ regard indépendant
# détecte des erreurs qu'un modèle ne voit pas dans sa propre sortie).
# Scope VOLONTAIREMENT restreint aux réponses contenant un bloc de code (même critère
# que le scanner déterministe) : appliquer ça à CHAQUE message ("quelle heure est-il ?")
# doublerait la latence pour zéro bénéfice — régression déjà vécue et corrigée (v2.125/
# v2.126, "Marvin reste à réfléchir"). Produit un BANDEAU visible (jamais une réécriture
# silencieuse de la réponse) : un texte auto-corrigé par un LLM sans supervision humaine
# est invérifiable, contraire à l'exigence de fiabilité prouvée de cette session.
# v2.185 — signalé en audit réel : sur "donne moi la commande pour installer hyper-v..." puis
# "la commande launtype pour que hyper v soit activé toujours", Marvin a appelé ssh_list PUIS
# exécuté réellement la commande localement (pc_run_powershell, escaladé jusqu'à
# pc_run_elevated) — alors que l'utilisateur demandait juste LE TEXTE de la commande, jamais son
# exécution. La règle d'or #14 existante couvrait déjà "écrire ≠ exécuter" pour un OS différent/
# une machine distante, mais pas ce cas précis (même OS, machine locale, mais aucun verbe
# d'exécution dans le message) — le prompt seul n'a pas suffi (plafond déjà documenté ailleurs,
# cf. deterministic-script-scanner-v2131). Filet déterministe : si le dernier message demande
# explicitement LA COMMANDE (texte) sans aucun verbe d'exécution, les outils qui exécutent
# réellement quelque chose sont bloqués pour ce tour — l'exception explicite ("lance-la",
# "exécute-la", "fais-le") réactive immédiatement l'exécution normale.
_EXECUTION_TOOLS = {"pc_run_command", "pc_run_powershell", "pc_run_elevated",
                     "ssh_exec", "ssh_exec_multi", "ssh_write_and_run",
                     # v2.185 — observé dans la même conversation réelle : ssh_list/ssh_server_info
                     # appelés sur des questions purement locales Windows, sans rapport avec la
                     # demande (déjà interdit par la règle d'or #10, mais pas respecté de façon
                     # fiable) — un utilisateur qui demande juste le TEXTE d'une commande n'a besoin
                     # d'aucune de ces deux investigations.
                     "ssh_list", "ssh_server_info"}

# Même au niveau Expert, une action sortante ou irréversible reste soumise à la validation
# humaine explicite. Expert accélère les opérations locales réversibles ; il ne transforme
# jamais « prépare/envisage » en envoi, suppression ou modification distante autorisée.
_ALWAYS_CONFIRM_TOOLS = {
    "email_send", "email_automation_run", "telegram_send", "itsm_ticket_create",
    "file_delete", "task_delete", "note_delete", "event_delete", "memory_delete",
    "ssh_exec", "ssh_exec_multi", "ssh_upload", "ssh_write_and_run",
    "system_cleanup", "long_task_start", "pc_gui_click", "pc_gui_type",
    "code_workspace_start", "code_workspace_control",
}


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
    try:
        _hist = int(db.get_setting("history_depth") or MAX_CONTEXT_MESSAGES)
    except Exception:
        _hist = MAX_CONTEXT_MESSAGES
    _overflow = messages[:max(0, len(messages) - _hist)]   # messages anciens → compactés en résumé
    recent = messages[max(0, len(messages) - _hist):]
    ollama_msgs = _to_ollama_messages(recent)

    # ── Injecter les vrais chemins dans le premier tour de chaque conversation ─
    # Si c'est le 1er message (nouveau conv), on injecte les paths comme 1er tool result
    # pour que le modèle "voie" les vrais chemins avant de répondre.
    if len(messages) <= 1 and not _tool_suppression:
        from tools import execute_pc_get_real_paths
        try:
            real_paths = await execute_pc_get_real_paths({})
            paths_injection = {
                "role": "tool",
                "content": json.dumps({
                    "type": "system_paths_discovery",
                    **real_paths,
                }, ensure_ascii=False),
            }
            # Insérer juste avant le dernier message utilisateur
            if ollama_msgs and ollama_msgs[-1]["role"] == "user":
                ollama_msgs.insert(-1, {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "pc_get_real_paths", "arguments": {}}}],
                })
                ollama_msgs.insert(-1, paths_injection)
        except Exception:
            pass

    # ── Charger les mémoires ──────────────────────────────────────────────────
    try:
        memories = db.get_memories()
    except Exception:
        memories = []

    # ── Lire le niveau de permission ─────────────────────────────────────────
    try:
        perm_raw = db.get_setting("permission_level")
        permission_level = int(perm_raw) if perm_raw is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        permission_level = DEFAULT_PERMISSION_LEVEL

    # Connaissances apprises : rappel SÉMANTIQUE → injecté EN TÊTE (priorité absolue,
    # sinon noyé dans le long prompt de capacités et ignoré par le modèle).
    # Rappel mémoire (embed) + filtrage des outils (embed) = 2 opérations INDÉPENDANTES.
    # On les lance EN PARALLÈLE (gain de latence, résultat identique) et on construit le
    # prompt système pendant ce temps.
    _cortex_advise_only = (
        "autonomy" in _cortex_plan.get("explicit_axes", [])
        and _cortex_plan["resolved"]["autonomy"] == "advise"
    )
    use_tools = (
        MODEL_PROFILES.get(profile_name, {}).get("tools", True)
        and not _tool_suppression
        and (not _cortex_advise_only or bool(_required_tool_names))
    )

    async def _recall_learned():
        try:
            import learning
            return learning.recall_block(await learning.recall(_user_query))
        except Exception:
            return ""

    async def _match_skill():
        try:
            import skills
            # v2.190 — le contexte précédent n'est repris que pour un vrai follow-up
            # anaphorique (« vas-y », « fais-le »), plus pour toute phrase de 4 mots.
            match_text = skill_match_text(messages, _user_query)
            return await skills.match(match_text)
        except Exception:
            return None

    _recall_task = (
        asyncio.create_task(_recall_learned())
        if _tool_suppression != "quiz_answer"
        else None
    )
    _tools_task = asyncio.create_task(_filter_relevant_tools(messages, profile_name)) if use_tools else None
    _skill_task = asyncio.create_task(_match_skill()) if not _tool_suppression else None

    system_prompt = _build_system_prompt(memories, permission_level)
    system_prompt += _cortex.prompt_block(_cortex_plan)
    if _tool_suppression:
        system_prompt += (
            "\n\n=== MODE RÉPONSE DIRECTE ===\n"
            "Aucun outil ne doit être appelé pour ce tour. Réponds uniquement au message "
            "de l'utilisateur dans le chat, sans chercher, diagnostiquer, mémoriser ni créer de fichier."
        )
    if _required_tool_names:
        system_prompt += (
            "\n\n=== OUTIL(S) IMPOSÉ(S) PAR LE CONTRAT ===\n"
            f"Tu dois obligatoirement exécuter : {', '.join(sorted(_required_tool_names))}. "
            "Tu ne peux pas conclure avant leur exécution réelle."
        )

    # v2.142 — « Projects » avec instructions persistantes (équivalent Claude/ChatGPT
    # Projects) : si cette conversation est rattachée à un projet ayant des instructions,
    # elles sont injectées ici — s'appliquent à TOUTE conversation du projet, sans avoir
    # à les répéter à chaque fois. Best-effort (jamais bloquant).
    try:
        _conv = db.get_conversation(conversation_id)
        _pid = (_conv or {}).get("project_id")
        if _pid:
            _project = db.get_project(_pid)
            _pinstr = (_project or {}).get("instructions") or ""
            if _pinstr.strip():
                system_prompt += (
                    f"\n\n=== INSTRUCTIONS DU PROJET « {_project.get('name', '')} » ===\n"
                    f"{_pinstr.strip()}\n"
                    "(Ces instructions s'appliquent à toute cette conversation, en plus des règles ci-dessus.)"
                )
    except Exception:
        pass

    # v2.174 — identité document persistante (auteur/organisation/en-tête/pied de page par
    # défaut, réglée via document_identity_set) injectée ici pour que le modèle SACHE déjà
    # si elle est connue avant de décider s'il doit la demander (règle d'or #16) — évite de
    # redemander à chaque document une fois réglée une première fois.
    try:
        _doc_identity = db.get_setting("document_identity")
        if isinstance(_doc_identity, dict) and any(_doc_identity.values()):
            _di_lines = "\n".join(f"- {k} : {v}" for k, v in _doc_identity.items() if v)
            system_prompt += (
                "\n\n=== IDENTITÉ DOCUMENT DÉJÀ CONNUE (ne redemande PAS ces infos) ===\n"
                f"{_di_lines}\n"
                "(file_create_pdf/file_create_docx l'appliquent déjà automatiquement en repli — "
                "inutile de la repasser en argument sauf pour LA remplacer pour ce document précis.)"
            )
    except Exception:
        pass

    # SKILL : si une compétence (fichier Markdown) correspond à la demande, on injecte sa
    # MÉTHODE dans le prompt (Marvin l'applique avec ses outils déjà vérifiés). Couche-prompt
    # uniquement → aucune exécution de code, donc aucune faille « à la OpenClaw ».
    _skill = None
    try:
        _skill = await _skill_task if _skill_task else None
    except Exception:
        _skill = None
    if _skill:
        rel = _skill.get("related") or []
        rel_line = (f"\nCompétences liées que tu peux enchaîner si besoin : {', '.join(rel)}." if rel else "")
        system_prompt += (
            f"\n\n## 📋 Compétence activée : {_skill['name']}\n"
            f"Quand : {_skill['description']}\n\n{_skill['body']}{rel_line}\n\n"
            "### Mode opératoire agentique (IMPÉRATIF)\n"
            "1. AGIS MAINTENANT : exécute le PREMIER outil pertinent via un VRAI appel d'outil. "
            "⛔ N'écris JAMAIS un appel d'outil sous forme de texte, de JSON ou de bloc ```...``` — "
            "fais l'appel réel ; le système exécutera l'outil et te renverra le résultat.\n"
            "2. NE déroule PAS tout le plan à l'avance en texte : un seul outil à la fois, puis observe.\n"
            "3. Après CHAQUE outil, LIS le résultat réel et dis ce qu'il signifie — ne suppose JAMAIS le résultat.\n"
            "4. Si une étape échoue ou surprend, AUTO-CORRIGE (essaie une alternative) au lieu d'abandonner ou d'inventer.\n"
            "5. VÉRIFIE que le problème est réellement résolu AVANT de conclure (refais un test quand c'est possible).\n"
            "6. CONCLUS : diagnostic clair + preuve (résultats obtenus) + action recommandée. Si non résolu, dis-le honnêtement et propose l'étape suivante.")
        # 🥇 GOLDEN PATH : si cette compétence a DÉJÀ réussi, on injecte la séquence d'outils
        # gagnante comme EXEMPLE few-shot. Pour un petit modèle local, imiter un déroulé réel
        # est bien plus fiable que suivre des consignes → exécution plus rapide et plus juste.
        try:
            import skills as _skg
            _golden = _skg.get_golden_trace(_skill["name"])
        except Exception:
            _golden = None
        if _golden and _golden.get("calls"):
            _steps = "\n".join(
                f"{i+1}. `{c.get('tool')}`" + (f" — {c.get('args')}" if c.get("args") else "")
                for i, c in enumerate(_golden["calls"][:8]))
            system_prompt += (
                f"\n\n### ✅ Déroulé DÉJÀ RÉUSSI (exemple à imiter)\n"
                f"Pour une demande similaire, cette SÉQUENCE d'outils a fonctionné. Réutilise-la en "
                f"adaptant les paramètres au cas présent — c'est la voie la plus efficace :\n{_steps}")
        # 📦 RESSOURCES : injecte le contenu de référence embarqué (petites ressources inline ;
        # gros fichiers / binaires → chemins à lire à la demande via file_read).
        try:
            import skills as _skr
            _resblock = _skr.resources_prompt_block(_skill["name"])
            if _resblock:
                system_prompt += _resblock
        except Exception:
            pass
        # Une compétence pilote des OUTILS → un petit modèle (chat 3b) suit mal la méthode et
        # choisit le mauvais outil. On bascule sur le modèle AGENT (plus fiable) pour l'exécuter.
        if profile_name == "chat" and _skill.get("tools"):
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

    learned_block = await _recall_task if _recall_task else ""
    # Position la PLUS saillante : on injecte la mémoire dans le dernier message
    # utilisateur (sinon noyée dans le long prompt système et ignorée par le modèle).
    if learned_block and ollama_msgs and ollama_msgs[-1].get("role") == "user":
        u = ollama_msgs[-1].get("content", "")
        if isinstance(u, str) and u.strip():
            ollama_msgs[-1]["content"] = (
                learned_block.strip()
                + "\n\n(Utilise ces informations mémorisées si elles sont pertinentes pour répondre, "
                "sans les répéter mot pour mot.)\n\n— Demande : " + u
            )

    # ── Filtrage intelligent des outils (déjà lancé en parallèle ci-dessus) ──
    tools_payload = (await _tools_task) if _tools_task else []
    # Outil explicite : n'offrir QUE celui-là au modèle (pas de distraction possible).
    if _explicit_tool_names and use_tools:
        tools_payload = [
            s for s in TOOLS_SPEC if s.get("function", {}).get("name") in _explicit_tool_names
        ] or tools_payload
    if _required_tool_names and use_tools:
        have = {t.get("function", {}).get("name") for t in tools_payload}
        for spec in TOOLS_SPEC:
            if spec.get("function", {}).get("name") in _required_tool_names - have:
                tools_payload.append(spec)
    # Une skill peut suggérer des outils précis → on s'assure qu'ils sont bien proposés au modèle.
    if _skill and _skill.get("tools") and use_tools:
        have = {t.get("function", {}).get("name") for t in tools_payload}
        for spec in TOOLS_SPEC:
            nm = spec.get("function", {}).get("name")
            if nm in _skill["tools"] and nm not in have:
                tools_payload.append(spec)
                have.add(nm)

    # ── Boucle d'appel d'outils ───────────────────────────────────────────────
    assistant_text_accum = ""       # texte de la réponse courante
    tool_calls_for_db: list = []    # tool calls de l'étape courante
    tool_results_for_db: list = []  # résultats
    _runner_state = _RunnerState()
    _executed_tool_names = _runner_state.executed_tool_names

    async def _cortex_disagreement_escalation(critique_text: str | None, answer: str):
        """Déclenche le Council 5 seulement après un désaccord réel du vérificateur,
        et uniquement si l'utilisateur a explicitement choisi cette politique."""
        if not critique_text:
            return None
        if "review" not in _cortex_plan.get("explicit_axes", []):
            return None
        if _cortex_plan["resolved"]["review"] != "council_if_disagreement":
            return None
        call_id = f"cortex-council-{uuid.uuid4().hex[:10]}"
        args = {
            "question": _user_query,
            "evidence": ("Réponse initiale :\n" + answer[:5000] +
                         "\n\nDésaccord du vérificateur :\n" + critique_text[:1800]),
        }
        try:
            result = await TOOLS_REGISTRY["ai_model_council"](args)
        except Exception as exc:
            result = {"error": f"Escalade Council impossible : {exc}"}
        final = result.get("answer") if isinstance(result, dict) else None
        block = ("\n\n---\n🏛️ **Arbitrage Council 5 déclenché par désaccord**\n" + final) if final else ""
        return call_id, args, result, block

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
    _outcome_recorded = False
    # v2.138 — compensation de la fiabilité composée : la littérature 2026 sur les agents LLM
    # documente qu'à 95% de fiabilité PAR appel, une chaîne de 8 outils ne réussit globalement
    # qu'à ~66% (les erreurs se composent). Pas de changement de comportement ici — juste une
    # trace visible (audit.jsonl) dès qu'un tour dépasse 8 appels, pour que ce signal soit
    # repérable lors d'un futur audit sans avoir à recompter manuellement les tool_start comme
    # fait à la main pour le diagnostic v2.136.

    def _finalize_skill_outcome():
        """Enregistre l'issue de la compétence active et, si un OUTIL a échoué (mauvais
        outil/commande/paramètre — pas un simple résultat négatif), programme un
        AUTO-UPGRADE en arrière-plan (Marvin ré-écrit la compétence ; ancienne version
        archivée). Appelé aux 2 sorties (réponse finale ET MAX_TOOL_STEPS). Retourne un
        message SSE à yield, ou None."""
        nonlocal _outcome_recorded
        if _outcome_recorded or not (_skill and _skill.get("tools")):
            return None
        _outcome_recorded = True
        try:
            import skills as _sk, tools as _tm3
            _executed = _runner_state.tool_count
            _ok = _runner_state.succeeded
            _detail = f"{_runner_state.failed_tools} erreur(s) d'outil sur {_executed} appel(s)."
            _trace = ("Demande: " + (_user_query or "")[:300] + "\n"
                      + "\n".join(_run_trace[-14:])
                      + "\nRéponse finale: " + (full_content or "")[:400])
            _sk.record_outcome(_skill["name"], _ok, _detail, transcript=_trace)
            # 🥇 Succès propre avec au moins un outil → mémoriser le déroulé gagnant
            # (golden path) ; skills garde le plus COURT → la compétence devient + efficace.
            if _ok and _runner_state.successful_tools > 0 and _run_calls:
                try:
                    _sk.record_success_trace(_skill["name"], _run_calls, _user_query)
                except Exception:
                    pass
            if not _ok:
                _all_names = [t.get("function", {}).get("name") for t in TOOLS_SPEC]
                _sk_name = _skill["name"]

                async def _auto_upgrade():
                    async def _g(p):
                        # v2.122 — model=None laisse _ollama_generate consulter le routage
                        # cloud/sensibilité (cloud_routing.resolve_model) sur le PROMPT réel
                        # (transcript de l'échec inclus) plutôt que de pré-résoudre en local
                        # à l'aveugle — reste local automatiquement si le transcript contient
                        # une donnée sensible, sinon peut bénéficier du cloud si configuré.
                        return await _tm3._ollama_generate(p, model=None, timeout=240)
                    await _sk.upgrade_skill(_sk_name, _g, reason=_detail, transcript=_trace, tool_names=_all_names)

                _ut = asyncio.create_task(_auto_upgrade())
                _BG_LEARN_TASKS.add(_ut)
                _ut.add_done_callback(_BG_LEARN_TASKS.discard)
                return _sse({"type": "skill_upgrade", "skill": _sk_name,
                             "message": f"🔧 Compétence « {_sk_name} » : un outil a échoué — auto-amélioration en arrière-plan."})
        except Exception:
            pass
        return None

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
        full_content = ""
        tool_calls_found: list[dict] = []

        try:
            _request = _OllamaChatRequest(
                model=active_model,
                system_prompt=system_prompt,
                messages=ollama_msgs,
                tools=tools_payload,
                options=_ollama_options,
            )
            async for event in _stream_ollama_chat(_ollama_client, OLLAMA_URL, _request):
                if event.kind == "thinking":
                    yield _sse({"type": "thinking", "text": event.text})
                elif event.kind == "text":
                    full_content += event.text
                    if not _blocking_outcomes:
                        yield _sse({"type": "text", "text": event.text})
                elif event.kind == "tool_calls":
                    tool_calls_found = list(event.tool_calls)
        except Exception as exc:
            yield _sse(_ollama_error_event(
                exc,
                model=active_model,
                base_url=OLLAMA_URL,
                read_timeout=300,
            ))
            return

        # ── Filet de sécurité : appels d'outils écrits en TEXTE/JSON ───────────
        # Si le modèle n'a pas émis d'appel natif mais a décrit des appels en JSON
        # dans le texte (fréquent avec les compétences pas-à-pas), on les récupère
        # pour AGIR réellement au lieu de seulement « parler ».
        if not tool_calls_found and full_content:
            _allowed = {t.get("function", {}).get("name") for t in tools_payload}
            _salvaged = _salvage_text_tool_calls(full_content, _allowed)
            if _salvaged:
                tool_calls_found = _salvaged

        # Une demande explicite de Council est un contrat, pas une simple suggestion au LLM.
        # S'il tente de conclure sans l'appeler, ou s'il remplit presque tout le budget avec
        # des recherches web, on injecte l'appel réel en conservant les autres outils du tour.
        _required_injection = _inject_required_tool_calls(
            required_names=_required_tool_names,
            executed_names=_executed_tool_names,
            tool_calls=tool_calls_found,
            step=step,
            max_steps=_max_tool_steps,
            context=_RequiredToolContext(
                user_query=_user_query,
                workspace_normalized_query=_workspace_norm,
                workspace_mission_id=_workspace_mission_id,
                workspace_action=_workspace_action,
                messages=messages,
            ),
        )
        tool_calls_found = _required_injection.tool_calls
        if _required_injection.injected and full_content.strip():
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
            # Sauvegarder le message assistant de cette étape en BD
            tc_for_db = [
                {
                    "toolCallId": str(uuid.uuid4()),
                    "toolName": tc["function"]["name"],
                    "args": tc["function"].get("arguments", {}),
                }
                for tc in tool_calls_found
            ]
            db.create_message(conversation_id, "assistant", full_content, tool_calls=tc_for_db)

            # Ajouter le message assistant à la boucle Ollama
            ollama_msgs.append({
                "role": "assistant",
                "content": full_content,
                "tool_calls": tool_calls_found,
            })

            tool_results_for_db_step = []

            for tc, tc_db in zip(tool_calls_found, tc_for_db):
                _prepared_call = _prepare_tool_call(
                    tc["function"]["name"],
                    tc["function"].get("arguments", {}),
                )
                tool_name = _prepared_call.name
                tool_args = _prepared_call.arguments
                _read_signature = _prepared_call.read_signature
                tc["function"]["name"] = tool_name
                tc_db["toolName"] = tool_name

                tool_call_id = tc_db["toolCallId"]

                # Notifier le frontend — début d'outil
                yield _sse({
                    "type": "tool_start",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "args": tool_args,
                })

                _tool_t0 = time.time()
                tool_args = _inject_internal_tool_context(
                    tool_name, tool_args, conversation_id
                )
                # ── Outil explicite : bloque toute substitution ────────────────
                # Le modèle propose parfois un outil "proche" au lieu de celui demandé par
                # son nom exact (ex: net_ping au lieu de file_find). tools_payload a déjà été
                # restreint à _explicit_tool_names ; ce garde-fou couvre le cas résiduel où le
                # modèle appelle quand même un autre nom (halluciné ou substitué).
                if _read_signature and _read_signature in _read_call_signatures:
                    result = {
                        "success": False,
                        "duplicate_poll_blocked": True,
                        "message": (
                            "Statut Code Workspace déjà lu pendant ce tour. N'interroge pas "
                            "la mission en boucle : réponds avec le dernier état observé. "
                            "Le superviseur Auto continue en arrière-plan."
                        ),
                    }
                elif _explicit_tool_names and tool_name not in (_explicit_tool_names | _required_tool_names):
                    requested = ", ".join(sorted(_explicit_tool_names))
                    result = {
                        "error": (
                            f"⛔ Outil bloqué : tu as explicitement demandé {requested}. "
                            f"Marvin ne peut pas appeler '{tool_name}' à la place ce tour-ci."
                        ),
                        "blocked_by_explicit_tool": True,
                        "requested_tools": sorted(_explicit_tool_names),
                    }
                # ── v2.185 : « donne-moi la commande » ≠ « exécute-la » ─────────
                # Filet déterministe (le prompt seul ne suffisait pas, cf. note plus haut) :
                # aucun verbe d'exécution dans le message → les outils qui exécutent réellement
                # quelque chose sont bloqués, Marvin doit répondre en texte à la place.
                elif _command_text_only and tool_name in _EXECUTION_TOOLS:
                    result = {
                        "error": (
                            "⛔ L'utilisateur a demandé LE TEXTE de la commande, pas son exécution "
                            f"— '{tool_name}' est bloqué ce tour-ci. Réponds directement avec la "
                            "commande en texte (bloc de code), sans l'exécuter. Si l'utilisateur "
                            "veut vraiment l'exécuter, il te le dira explicitement (« lance-la », "
                            "« exécute »)."
                        ),
                        "blocked_command_text_only": True,
                    }
                # ── Validation des arguments (v2.138) ──────────────────────────
                elif (_missing_msg := _validate_tool_args(tool_name, tool_args)):
                    result = {"error": _missing_msg, "validation_failed": True}
                # ── Vérification des permissions ──────────────────────────────
                elif permission_level == PERMISSION_SECURE and tool_name in SECURE_BLOCKED_TOOLS:
                    result = {
                        "error": (
                            f"🛡️ Permission refusée (niveau Sécurisé) : "
                            f"l'outil '{tool_name}' n'est pas autorisé. "
                            f"Passez en mode Standard ou Expert dans les Paramètres pour débloquer cette action."
                        )
                    }
                elif permission_level == PERMISSION_EXPERT:
                    # Expert accélère les actions locales réversibles. Les sorties et les
                    # suppressions restent volontairement non confirmées afin que l'exécuteur
                    # renvoie requiresConfirmation et demande un accord humain explicite.
                    if tool_name not in _ALWAYS_CONFIRM_TOOLS:
                        tool_args["confirmed"] = True
                    result = await _execute_registered_tool(
                        tool_name, tool_args, conversation_id, request_id,
                    )

                else:
                    # Niveau Standard (ou non défini) : comportement normal
                    result = await _execute_registered_tool(
                        tool_name, tool_args, conversation_id, request_id,
                    )

                _tool_duration_ms = int((time.time() - _tool_t0) * 1000)
                # v2.248 — contrat additif commun à tous les outils. Les champs historiques
                # restent intacts; `_contract` fournit un état, un code d'erreur et la
                # retryabilité lisibles de façon déterministe par le Chat et les superviseurs.
                if isinstance(result, dict):
                    try:
                        import engineering_runtime as _engineering_runtime
                        result = _engineering_runtime.normalize_tool_result(
                            tool_name, result, duration_ms=_tool_duration_ms,
                        )
                    except Exception:
                        pass

                if _read_signature:
                    _read_call_signatures.add(_read_signature)

                # 🛡️ AUTO-CRITIQUE : avant une action irréversible (qui attend confirmation),
                # une IA vérifie que l'action correspond bien à la demande. Si doute → averti.
                if (isinstance(result, dict) and result.get("requiresConfirmation")
                        and tool_name in DANGEROUS_TOOLS and _user_query):
                    try:
                        concern = await _critique_action(_user_query, tool_name, tool_args, model=active_model)
                        if concern:
                            result["message"] = (result.get("message", "") +
                                                  f"\n\n⚠️ Vérification de Marvin : {concern}")
                    except Exception:
                        pass

                # v2.133 — le filet v2.131/132 ne scannait que la réponse de chat visible, pas
                # le CONTENU des documents générés (file_create_pdf, document_generate...) — un
                # angle mort concret : le PDF GLPI qui a motivé tout ce chantier (v2.127) avait
                # son mot de passe root vidé et son `$(date...)` littéral dans l'argument
                # `content` d'un appel d'outil, jamais dans le texte de chat lui-même, donc le
                # scanner de la réponse finale ne l'aurait PAS attrapé. Scan des arguments texte
                # des outils de génération de document, AVANT que l'utilisateur ne parte
                # chercher le fichier généré.
                if tool_name in ("file_create_pdf", "document_generate", "billing_quote_pdf",
                                  "file_convert_docx_to_pdf") and isinstance(result, dict) and result.get("success"):
                    _doc_text = tool_args.get("content") or tool_args.get("body") or ""
                    if isinstance(_doc_text, str) and _doc_text:
                        _doc_warnings = _scan_dangerous_script_patterns(
                            _doc_text, require_code_fence=False, document_mode=True)
                        if _doc_warnings:
                            result["security_warning"] = (
                                "⚠️ Vérification automatique de sécurité — points à relire dans ce document avant de l'utiliser :\n"
                                + "\n".join(f"- {w}" for w in _doc_warnings)
                            )

                # Notifier le frontend — fin d'outil
                yield _sse({
                    "type": "tool_end",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "result": result,
                })

                # Un gate Forge négatif est bloquant. Le tour suivant reste tamponné : Marvin
                # ne peut plus diffuser une affirmation de succès contredisant le reçu réel.
                if tool_name in {"ai_test_forge", "ai_code_forge"}:
                    _runner_state.update_blocking_outcome(tool_name, result)

                await _record_tool_observation(_ToolObservation(
                    conversation_id=conversation_id,
                    user_query=_user_query,
                    tool_name=tool_name,
                    arguments=tool_args,
                    result=result,
                    duration_ms=_tool_duration_ms,
                ))

                # Suivi pour l'auto-réparation : compte OK/erreur + trace compacte.
                _long_chain_started = _runner_state.record_tool(
                    tool_name,
                    tool_args,
                    result,
                    tooling_failure=_is_tooling_failure(result),
                )
                if _long_chain_started:
                    _record_long_chain(_user_query, _runner_state.tool_count)

                tool_results_for_db_step.append({
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "result": result,
                })

                ollama_msgs.append({
                    "role": "tool",
                    "content": _compact_tool_result(result),
                })

            # Sauvegarder les résultats d'outils
            db.create_message(
                conversation_id, "tool",
                json.dumps(tool_results_for_db_step),
                tool_results=tool_results_for_db_step,
            )

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

            # Apprentissage en arrière-plan (sans bloquer) : le LLM « professeur »
            # extrait les faits durables + une Q/R réutilisable de cet échange.
            # ⚠️ Garder une référence à la tâche (sinon le GC peut la détruire avant exécution).
            try:
                import learning, tools as _tm
                # Stratégie d'apprentissage selon le MODE de performance :
                # - "resident" (petites machines) : réutilise le modèle DÉJÀ chargé (active_model)
                #   → aucun 2ᵉ modèle à charger (sinon, sur 4 Go, ça évince le 3b et fait ramer).
                # - "dedicated" (machines puissantes) : utilise un gros modèle (analysis/agent)
                #   pour une extraction de faits de meilleure qualité (la VRAM le permet).
                try:
                    _strategy = db.get_setting("learn_strategy") or "resident"
                except Exception:
                    _strategy = "resident"
                if _strategy == "dedicated":
                    # v2.122 — model=None laisse _ollama_generate consulter le routage
                    # cloud/sensibilité sur le PROMPT réel (contenu de l'échange) plutôt que
                    # de pré-résoudre en local à l'aveugle.
                    _learn_model = None
                else:
                    # "resident" : réutilise active_model déjà correctement routé pour ce
                    # tour (cloud si approprié, local si sensible) — pas de nouveau choix.
                    _learn_model = active_model
                async def _teacher(p):
                    return await _tm._ollama_generate(p, model=_learn_model, timeout=180)
                _t = asyncio.create_task(learning.learn_from_exchange(_user_query, full_content, _teacher))
                _BG_LEARN_TASKS.add(_t)
                _t.add_done_callback(_BG_LEARN_TASKS.discard)
            except Exception:
                pass

            # Auto-réparation des compétences (enregistre l'issue + auto-upgrade si échec).
            _up_msg = _finalize_skill_outcome()
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
    _up_msg = _finalize_skill_outcome()
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
