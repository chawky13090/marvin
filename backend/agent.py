"""
SecretaryAI Backend — Agent de streaming.
Appelle Ollama directement (HTTP), gère la boucle d'appel d'outils,
et produit des événements SSE pour le frontend.
"""
import asyncio
import base64
import json
import re
import time
import uuid
from functools import partial
from typing import AsyncIterator

import httpx

import cloud_routing as _cr
import database as db
from intent_guard import (
    skill_match_text, tool_suppression_reason, wants_command_text_only as _wants_command_text_only,
    wants_model_council, workspace_followup,
)
from agent_policy import (
    autotitle_from_text as _autotitle_from_text,
    exact_tool_mentions_from_text,
)
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
from config import (
    OLLAMA_URL, DEFAULT_MODEL, MAX_TOOL_STEPS, MAX_CONTEXT_MESSAGES,
    PERMISSION_SECURE, PERMISSION_EXPERT, DEFAULT_PERMISSION_LEVEL,
    SECURE_BLOCKED_TOOLS, DANGEROUS_TOOLS,
    MODEL_PROFILES, DATA_DIR,
)
from tools import TOOLS_REGISTRY, TOOLS_SPEC
import tools as _tools_mod

_exact_tool_mentions_from_text = partial(
    exact_tool_mentions_from_text,
    tool_names={spec.get("function", {}).get("name", "") for spec in TOOLS_SPEC},
)
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
def _log_tool_exception(tool_name: str, tool_args: dict, ex: Exception, conversation_id: str | None) -> dict:
    """v2.184 — un outil qui LÈVE une exception (pas un {"error": ...} propre) est plus
    probablement un vrai bug qu'un cas géré — capture le traceback COMPLET dans bug_log.jsonl
    (tool_executions/audit.jsonl ne gardent que str(ex), jamais la stack) pour un débogage
    effectif plus tard, sans avoir à reproduire. Best-effort, ne doit jamais lever à son tour."""
    try:
        import traceback as _tb
        import bug_log as _bug_log
        _bug_log.log_bug(
            "tool_exception", str(ex), context={"args": tool_args},
            traceback_str=_tb.format_exc(), conversation_id=conversation_id, tool_name=tool_name,
        )
    except Exception:
        pass
    return {"error": str(ex)}


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
_CRITIQUE_PROMPT_TMPL = (
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


async def _run_critique_pass(
    user_query: str, full_content: str, active_model: str, *, force: bool = False
) -> str | None:
    """Retourne le verdict du critique (texte des problèmes trouvés) ou None si le
    critique n'a rien trouvé / a échoué / ne s'applique pas à ce tour. Best-effort
    strict : aucune exception ne doit jamais empêcher l'envoi de la réponse principale."""
    if not force and "```" not in full_content:
        return None
    try:
        import cloud_routing as _cr2
        import tools as _tm2
        # Choisir un modèle DIFFÉRENT de celui qui a répondu (diversité de jugement,
        # cf. Mixture-of-Agents) — reste dans les modèles cloud déjà configurés par
        # l'utilisateur, jamais un choix arbitraire hors de ses réglages.
        critic_model = None
        if _cr2.is_cloud_model(active_model):
            _, _overrides = _cr2.get_cloud_config()
            for _m in _overrides.values():
                if _m and _m != active_model:
                    critic_model = _m
                    break
        prompt = _CRITIQUE_PROMPT_TMPL.format(
            query=(user_query or "")[:2000], response=full_content[:6000])
        verdict = await _tm2._ollama_generate(prompt, model=critic_model, timeout=90)
        verdict = (verdict or "").strip()
        if not verdict or verdict.upper().startswith("OK"):
            return None
        # Filet : un critique qui dégénère en sortie quasi vide (ex. juste "-", observé
        # en test réel sur un appel) ne doit jamais produire un bandeau vide/inutile —
        # mieux vaut ne rien afficher qu'un "problème" sans contenu substantiel.
        if len(re.sub(r"[\s\-•*]", "", verdict)) < 15:
            return None
        return verdict
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Filtrage intelligent des outils — réduit drastiquement le temps de réponse
# ══════════════════════════════════════════════════════════════════════════════

# Toujours inclure ces outils (ils sont compacts et utiles partout)
_ALWAYS_INCLUDE = {
    "pc_get_real_paths",
    "memory_save", "memory_list",
    "datetime_info",
}

# Repli BORNÉ quand aucun mot-clé métier ne matche : un petit jeu d'outils
# polyvalents, AU LIEU des ~245 specs (qui font un prompt énorme → réponse de
# plusieurs minutes, surtout sur petit GPU). Les noms inexistants sont ignorés.
_COMMON_TOOLS = {
    "web_search", "web_browse", "datetime_info", "weather",
    "task_create", "task_list", "task_update",
    "note_create", "note_list",
    "event_create", "event_list", "daily_briefing",
    "email_list", "email_digest",
    "system_search", "file_find", "pc_system_info",
    "translate", "calculator", "text_summarize",
}

# Mapping keyword → tools relevant for that keyword
# When user message contains these words, we include the matching tools
_KEYWORD_TOOLS = {
    # v2.183 — Génération de logo locale (GPU) : sans cette entrée, logo_generate/logo_list
    # sont enregistrés mais INVISIBLES sur les profils filtrés chat/agent (leçon répétée
    # cette session, cf. v2.93/v2.113 — un outil hors _KEYWORD_TOOLS n'est jamais proposé).
    ("logo", "logotype", "icône de marque", "icone de marque"):
        {"logo_generate", "logo_list"},

    # v2.184 — journal des vrais bugs (exceptions + traceback), pour un audit après usage
    # intensif sans supervision.
    ("journal des bugs", "liste les bugs", "quels bugs", "bug log", "erreurs recentes",
     "erreurs récentes", "qu'est ce qui a plante", "qu'est-ce qui a planté",
     "qu'est ce qui a bug", "qu'est-ce qui a buggé"):
        {"bug_log_list"},

    # v2.183 — changer le format d'un document déjà généré (docx<->pdf), sans le regénérer.
    ("plutot en word", "plutôt en word", "plutot en pdf", "plutôt en pdf", "convertis en word",
     "convertis en pdf", "convertir en word", "convertir en pdf", "en format word",
     "en format pdf", "change le format", "changer le format"):
        {"document_convert_format", "file_convert_docx_to_pdf"},

    # Météo
    ("météo", "meteo", "temps", "température", "temperature", "pluie", "neige",
     "vent", "prévision", "previsions", "il fait", "il pleut", "demain", "weather"):
        {"weather"},

    # Recherche web
    ("web", "internet", "google", "duckduckgo", "cherche sur", "recherche en ligne",
     "actualité", "news", "actu", "info", "trouve en ligne", "sur le net", "sur le web",
     "renseigne-toi", "renseigne toi"):
        {"web_search", "web_browse", "web_research"},

    # v2.142 — Recherche APPROFONDIE (« Deep Research ») : groupe de mots-clés SÉPARÉ et
    # plus restrictif que la recherche web générale ci-dessus — outil volontairement lent
    # (plusieurs minutes), ne doit apparaître que sur une demande explicite de profondeur/
    # exhaustivité, jamais sur "cherche sur le web" tout court.
    ("recherche approfondie", "recherche exhaustive", "recherche detaillee",
     "recherche détaillée", "rapport de recherche", "rapport complet sur",
     "rapport detaille sur", "rapport détaillé sur", "deep research", "enquete complete",
     "enquête complète", "analyse approfondie du web", "fouille le web"):
        {"web_deep_research"},

    # v2.142 — Conseil de plusieurs modèles IA (« Model Council ») : signal explicite
    # uniquement, jamais déclenché par défaut (coût de plusieurs appels LLM en parallèle).
    ("plusieurs ia", "plusieurs modeles", "plusieurs modèles", "conseil de modeles",
     "conseil de modèles", "demande a plusieurs", "demande à plusieurs",
     "differents modeles", "différents modèles", "model council", "deuxieme avis",
     "deuxième avis", "second avis", "autre ia", "autre modele", "autre modèle"):
        {"ai_model_council"},

    # v2.145 — Décomposition en sous-tâches parallèles (« Ultra mode »)
    ("plusieurs angles", "sous plusieurs angles", "decompose", "décompose",
     "sous-taches", "sous-tâches", "en parallele", "en parallèle", "plusieurs volets",
     "differents aspects", "différents aspects"):
        {"ai_subagents_run"},

    # v2.145 — Tâche longue autonome (« ChatGPT Work »)
    ("tache de fond", "tâche de fond", "en arriere-plan", "en arrière-plan",
     "pendant que je fais autre chose", "occupe-toi de", "occupe toi de",
     "fais avancer ce projet", "tache longue", "tâche longue", "sans supervision"):
        {"long_task_start", "long_task_status", "long_task_stop"},

    # v2.122 — Fraîcheur de l'information (règle d'or #8) : signaux qu'une réponse "de
    # mémoire" risque d'être périmée (version, actualité, disponibilité, événement récent) —
    # déclenche la recherche web même sans mention explicite de "web"/"internet".
    ("derniere version", "dernière version", "nouvelle version", "quoi de neuf",
     "encore d'actualite", "toujours d'actualite", "encore disponible", "existe encore",
     "vient de sortir", "recemment sorti", "récemment sorti", "sorti recemment",
     "en ce moment", "actuellement", "a jour", "à jour", "obsolete", "obsolète",
     "depuis quand", "cette annee", "cette année"):
        {"web_search", "web_research"},

    # Lire une page web
    ("url", "site", "page web", "lien", "http", "navigateur", "ouvre le site"):
        {"web_browse", "url_analyze", "web_browser_open", "web_research"},

    # Fichiers
    ("fichier", "dossier", "bureau", "documents", "downloads", "téléchargement",
     "fichiers", "dossiers"):
        {"system_search", "file_find", "file_list", "file_info", "file_read",
         "file_write", "file_delete", "file_rename", "file_move", "file_copy",
         "file_create_folder", "file_search_text", "pc_get_real_paths"},

    # Recherche dans fichiers
    ("trouve", "cherche", "où est", "ou est", "ou se trouve", "trouver", "*.pdf",
     "*.docx", "*.xlsx"):
        {"system_search", "system_search_content", "file_find", "file_search_text"},

    # Logiciels installés / inventaire logiciel
    ("logiciel installé", "logiciels installés", "logiciels installer", "inventaire logiciel",
     "liste des programmes", "programmes installés", "quels logiciels", "applications installées",
     "liste logiciels", "logiciels sur ce pc", "logiciels du pc"):
        {"pc_installed_software", "win_system_report", "pc_system_info"},

    # Installer / mettre à jour / désinstaller un logiciel (Winget) — bug réel corrigé
    # v2.113 : aucune entrée ne routait ici avant, le LLM tombait parfois sur du routage
    # sémantique fragile (marche pour "vlc" + "winget" explicite, échoue pour un nom moins
    # connu comme "victoria") → il "documentait" une installation (document_generate) au
    # lieu d'installer réellement. Stem court "instal" (pas "installe") pour matcher aussi
    # "install"/"installation" sans le "e" final — repéré en reproduisant le bug exact avec
    # le message original de l'utilisateur ("install le logiciel victoria", sans "e").
    # Matche aussi "installés"/"installer un inventaire" (substring) mais sans risque : ça
    # ne fait qu'AJOUTER winget_* à l'ensemble déjà proposé, jamais retirer pc_installed_software.
    ("instal", "télécharge et installe", "telecharge et installe",
     "mets à jour", "mets a jour", "met à jour", "met a jour", "mettre à jour", "mettre a jour",
     "désinstal", "desinstal", "winget"):
        {"winget_search", "winget_install", "winget_upgrade", "winget_uninstall",
         "winget_list_upgrades", "winget_list_installed"},

    # Recherche unifiée (tout à la fois)
    ("cherche partout", "recherche partout", "retrouve tout", "trouve tout ce qui", "tout ce qui concerne",
     "partout où", "dans tout", "recherche globale", "cherche dans tout"):
        {"unified_search", "system_search", "system_search_content", "document_ask"},

    # Recherche par CONTENU (fouiller le contenu des documents du PC)
    ("qui parle de", "qui contient", "où j'ai écrit", "ou j'ai ecrit", "le document sur",
     "le fichier où", "le fichier ou", "retrouve le document", "fouille", "fouiller",
     "dans le contenu", "à l'intérieur des fichiers", "le document qui mentionne",
     "cherche dans mes fichiers", "le contrat avec", "le devis de"):
        {"system_search_content", "system_search", "file_search_text", "document_ask"},

    # Documents Word/PDF/Excel
    ("word", "docx", "rédige un doc", "crée un doc", "lettre"):
        {"file_create_docx", "file_convert_docx_to_pdf", "pdf_read", "pdf_info",
         "docx_to_text", "text_summarize", "document_identity_set"},
    ("pdf", "convertis"):
        {"pdf_read", "pdf_info", "file_create_pdf", "file_convert_docx_to_pdf",
         "pdf_merge", "pdf_split", "pdf_rotate", "images_to_pdf",
         "pdf_watermark", "pdf_protect", "pdf_extract_images",
         "pdf_to_images", "pdf_ocr", "pdf_form_fields", "pdf_fill_form",
         "pdf_compress", "pdf_add_page_numbers", "document_identity_set"},
    ("compresse le pdf", "compresser le pdf", "allège le pdf", "réduis le pdf", "poids du pdf",
     "numérote le pdf", "numéro de page", "numéros de page", "pagination du pdf", "ajoute les pages"):
        {"pdf_compress", "pdf_add_page_numbers", "pdf_info"},
    # Synthèse vocale (text-to-speech)
    ("synthèse vocale", "synthese vocale", "lis à voix haute", "lis a voix haute", "voix off",
     "text to speech", "tts", "fais parler", "génère un audio", "transforme en audio",
     "transforme en voix", "voix off", "dis à voix haute", "narration"):
        {"text_to_speech"},
    # Graphique depuis des données
    ("graphique du csv", "graphique depuis", "trace le csv", "diagramme du csv", "camembert",
     "histogramme du csv", "graphe des données", "visualise les données", "courbe du csv"):
        {"csv_to_chart", "infographic_create", "csv_analyze"},
    ("fusionne les pdf", "fusionner pdf", "assemble les pdf", "combine les pdf",
     "découpe le pdf", "decouper le pdf", "sépare le pdf", "extraire des pages",
     "pivote le pdf", "tourne le pdf", "images en pdf", "photos en pdf",
     "filigrane sur le pdf", "protège le pdf", "protege le pdf", "mot de passe pdf",
     "chiffre le pdf", "extraire les images du pdf", "confidentiel pdf",
     "pdf scanné", "pdf scanne", "ocr du pdf", "ocr pdf", "texte du pdf scanné",
     "pdf en images", "pages du pdf en png", "remplis le formulaire", "champs du formulaire",
     "formulaire pdf"):
        {"pdf_merge", "pdf_split", "pdf_rotate", "images_to_pdf", "pdf_info",
         "pdf_watermark", "pdf_protect", "pdf_extract_images",
         "pdf_to_images", "pdf_ocr", "pdf_form_fields", "pdf_fill_form"},
    # Briefing du jour
    ("ma journée", "ma journee", "briefing du jour", "fais le point", "point du jour",
     "que dois-je faire aujourd", "résumé de ma journée", "mon programme", "quoi de neuf"):
        {"daily_briefing", "task_list", "email_digest", "event_list"},
    # Agenda / rendez-vous
    ("rendez-vous", "rendez vous", "rdv", "agenda", "planifie", "planifier", "agender",
     "mon planning", "mes rendez", "réunion", "reunion", "ajoute un événement",
     "ajoute un evenement", "note dans l'agenda", "quels rdv", "quel rendez"):
        {"event_create", "event_list", "event_update", "event_delete", "daily_briefing",
         "calendar_subscriptions", "calendar_sync"},
    # Telegram (alertes téléphone)
    ("telegram", "préviens-moi sur mon téléphone", "envoie sur mon téléphone",
     "envoie-moi un message", "notifie-moi sur telegram"):
        {"telegram_send"},
    # Génération de documentation (notes → Word)
    ("rédige", "redige", "génère un document", "genere un document", "fais-moi un rapport",
     "fais moi un rapport", "rapport d'intervention", "dossier professionnel", "dossier pro",
     "document word", "fichier word", "rédaction", "mets en forme un document",
     "procédure technique", "cahier des charges", "compte-rendu", "compte rendu",
     "génère une doc", "rédige une doc"):
        {"document_generate"},
    # v2.175 — documentation à partir des captures d'écran attachées au chat
    ("mes captures", "mes screenshots", "mes screens", "compile mes captures",
     "documente mon travail", "documentation de mon travail", "captures d'écran",
     "captures d ecran", "capture d'écran", "capture d ecran", "screenshot", "screenshots"):
        {"screenshot_list", "doc_generate_from_screenshots"},
    # Affiner une section d'un document généré
    ("développe la partie", "developpe la partie", "développe la section", "complète la section",
     "complete la section", "approfondis", "étoffe", "etoffe", "raccourcis la section",
     "reformule la partie", "ajoute un tableau dans", "affine la section", "détaille la partie"):
        {"document_refine_section", "document_generate"},
    # Documents (RAG : parle à tes documents)
    ("parle à mes documents", "parle a mes documents", "dans mes documents", "mes documents",
     "indexe", "indexer", "que dit le contrat", "que dit le document", "selon le document",
     "selon le pdf", "cherche dans le", "interroge", "pose une question au document",
     "apprends ce dossier", "lis ce document et", "base de connaissance", "ma documentation"):
        {"document_index", "document_ask", "document_list", "document_forget", "system_search_content"},
    # Agendas connectés (abonnements iCal / Google / Outlook)
    ("connecte mon agenda", "connecter mon agenda", "connecte mon calendrier",
     "abonne", "abonnement", "ical", "lien ics", "agenda google", "calendrier google",
     "agenda outlook", "synchronise mon agenda", "synchroniser l'agenda", "mets à jour mes agendas",
     "agendas connectés", "agenda externe"):
        {"calendar_subscribe", "calendar_subscriptions", "calendar_unsubscribe", "calendar_sync",
         "event_list", "daily_briefing"},

    # PowerPoint
    ("powerpoint", "pptx", "présentation", "presentation", "diaporama", "diapo",
     "slides", "slide", "deck", "support de présentation"):
        {"pptx_create", "pptx_read"},
    # Conversions bureautiques
    ("csv en excel", "csv vers excel", "convertis le csv", "excel en csv", "xlsx en csv",
     "convertis le word", "word en texte", "docx en texte", "extrais le texte du word",
     "docx en markdown", "word en markdown"):
        {"csv_to_xlsx", "xlsx_to_csv", "docx_to_text", "file_create_xlsx"},
    # Résumé / synthèse IA
    ("résume", "resume", "résumé", "synthèse", "synthese", "synthétise", "tl;dr", "tldr",
     "points clés", "points d'action", "fais-moi un résumé", "résume ce document"):
        {"text_summarize", "pdf_read", "docx_to_text"},
    ("excel", "xlsx", "tableau", "tableur", "csv"):
        {"file_create_xlsx", "xlsx_read", "csv_analyze", "csv_to_xlsx", "xlsx_to_csv", "csv_to_chart"},

    # Agenda (local prioritaire + Google si demandé)
    ("calendrier", "agenda", "rendez-vous", "événement", "evenement", "rdv", "réunion"):
        {"event_create", "event_list", "event_update", "event_delete",
         "calendar_list", "calendar_create", "calendar_update", "calendar_delete"},

    # Emails
    ("email", "mail", "courriel", "gmail", "outlook", "boîte de réception", "envoie un mail",
     "boîte mail", "boite mail", "mes mails", "quelle boîte", "quels comptes mail",
     "réponds au mail", "reponds au mail", "réponse au mail", "rédige une réponse",
     "redige une reponse", "répondre à ce mail", "repondre a ce mail", "brouillon de réponse",
     "résume ce mail", "resume ce mail", "résume l'email", "résume mes mails",
     "briefing", "brief mes mails", "que dois-je traiter", "mails importants",
     "trie mes mails", "priorise mes mails", "fais le point sur mes mails",
     "réponse automatique", "reponse automatique", "mode autonome", "automatise mes mails",
     "traite mes mails", "réponds automatiquement", "prépare les réponses",
     "crée une tâche depuis", "transforme ce mail en tâche", "tâche depuis ce mail", "email en tâche",
     "pièce jointe", "piece jointe", "résume le pdf reçu", "résume la pièce jointe", "attachment",
     "surveille mes mails", "mails importants", "notifie", "notification", "alerte mail", "préviens-moi",
     "règle de classement", "classe mes mails", "trie automatiquement", "range mes mails", "filtre mail"):
        {"email_accounts", "email_list", "email_read", "email_search", "email_send",
         "email_draft_reply", "email_summarize", "email_digest", "email_automation_run", "email_to_task",
         "email_attachment_summary", "email_watch_check", "email_apply_rules"},

    # Calcul / maths
    ("calcul", "calculer", "calcule", "combien", "+ * -", "sqrt", "math",
     "racine", "factoriel", "puissance"):
        {"calculator"},

    # Date / heure
    ("date", "heure", "fuseau", "timezone", "tokyo", "new york", "maintenant",
     "aujourd'hui", "demain", "hier"):
        {"datetime_info"},

    # Traduction
    ("traduit", "traduis", "traduction", "translate", "anglais", "espagnol",
     "allemand", "italien", "chinois", "japonais", "arabe", "russe", "portugais"):
        {"translate"},

    # Conversion
    ("convertit", "convertis", "conversion", "km en", "kg en", "miles", "celsius",
     "fahrenheit", "litres", "gallons", "mo en", "go en"):
        {"unit_convert"},

    # Mot de passe
    ("mot de passe", "password", "mdp", "pin", "génère un mdp", "code secret"):
        {"password_generate"},

    # Hash / crypto / base64
    ("hash", "sha256", "sha512", "md5", "checksum", "empreinte", "intégrité"):
        {"hash_compute"},
    ("base64", "encode", "decode", "encodage"):
        {"base64_tool"},

    # PC / système
    ("pc", "système", "ordinateur", "ram", "cpu", "mémoire", "disque", "processus",
     "fenêtre", "fenêtres", "notification", "presse-papiers", "clipboard",
     "nettoie", "nettoyer", "nettoyage", "espace disque", "libère de l'espace",
     "fichiers temporaires", "temp", "gros fichiers", "plus gros fichiers",
     "qui prend de la place", "ce qui prend de la place"):
        {"pc_system_info", "pc_process_list", "pc_window_list", "pc_notify",
         "pc_clipboard_get", "pc_clipboard_set", "win_system_report", "win_disk_info",
         "system_cleanup", "file_large_finder"},

    # Lancer une application / ouvrir un fichier ou dossier
    ("lance", "lancer", "ouvre", "ouvrir", "démarre", "demarre", "exécute", "execute",
     "application", "appli", "logiciel", "programme", "chrome", "word", "excel", "spotify",
     "navigateur", "explorateur", "parcourir", "navigue", "naviguer", "arborescence",
     "explore", "explorer", "dossier", "presse-papier", "copie dans", "colle"):
        {"pc_app_launch", "pc_open_file", "pc_browse", "pc_clipboard_get", "pc_clipboard_set",
         "system_search", "file_find", "file_list"},

    # Diagnostic Windows avancé (v2.31, élargi v2.134 avec température/S.M.A.R.T./event log ciblé)
    ("diagnostic", "rapport système", "état du pc", "santé du pc", "uptime",
     "démarrage", "boot", "tâches planifiées", "scheduled", "config réseau",
     "configuration réseau", "doublons", "fichiers en double", "services windows",
     "redémarrage", "lent", "ralenti", "surchauffe", "chauffe", "température",
     "plantage", "crash", "bsod", "écran bleu", "problème logiciel", "problème physique",
     "problème matériel", "contrôle du pc", "controle du pc"):
        {"win_system_report", "win_uptime", "win_startup_programs",
         "win_scheduled_tasks", "win_network_config", "win_disk_info",
         "win_services_list", "win_service_action", "win_event_log",
         "file_duplicate_finder", "pc_hardware_temps", "pc_disk_smart_health",
         "pc_event_log_errors", "pc_hardware_specs", "win_firewall_status",
         "pc_driver_check"},

    # Pare-feu (v2.137)
    ("pare-feu", "firewall", "port ouvert", "règle entrante", "règle sortante"):
        {"win_firewall_status"},

    # Pilotes (v2.137)
    ("pilote", "driver", "dernière version pilote", "mise à jour pilote"):
        {"pc_driver_check", "pc_hardware_specs"},

    # Tendance de santé système (v2.138)
    ("tendance", "évolution", "ça empire", "ca empire", "dans combien de temps",
     "va se remplir", "disque plein bientôt", "historique de santé"):
        {"pc_health_trend"},

    # Fiabilité des outils (v2.138)
    ("outils échouent", "outils qui échouent", "taux d'échec", "fiabilité des outils",
     "quels outils marchent le moins bien"):
        {"pc_tool_reliability"},

    # Traçabilité de conversation (v2.139)
    ("pourquoi ça a été lent", "pourquoi c'était lent", "combien de temps a pris",
     "chronologie de la conversation"):
        {"pc_conversation_trace"},

    # Inventaire réseau persistant (v2.139)
    ("inventaire réseau", "inventaire du réseau", "appareils du réseau", "appareils connectés",
     "quels appareils sont sur le réseau"):
        {"net_inventory_scan", "net_inventory_list", "net_inventory_annotate"},

    # Connecteurs ITSM/ticketing (v2.139)
    ("glpi", "ticket", "tickets", "ouvre un ticket", "crée un ticket", "gestion de parc",
     "itsm"):
        {"itsm_ticket_list", "itsm_ticket_create", "itsm_asset_list"},

    # Capture d'écran
    ("capture", "screenshot", "écran", "ocr"):
        {"pc_screenshot", "screen_ocr", "ocr_extract"},

    # Agent GUI local — clic/frappe dans une fenêtre (v2.149)
    ("clique sur", "clique dans", "clic sur", "coche la case", "remplis le champ",
     "tape dans le champ", "appuie sur le bouton", "clique le bouton", "clic dans la fenetre",
     "clic dans la fenêtre"):
        {"pc_gui_read", "pc_gui_click", "pc_gui_type"},

    # Réseau
    ("ping", "réseau", "wifi", "ip", "dns", "traceroute", "scan de port", "whois",
     "nmap", "scan réseau", "certificat", "tls", "ssl", "https", "sweep", "sous-réseau",
     "subnet", "adresse mac", "bannière", "port ouvert", "site web accessible", "connectivité"):
        {"net_ping", "net_port_scan", "net_dns_lookup", "net_traceroute",
         "net_whois", "net_scan_local", "ip_info", "win_network_config",
         "net_nmap_scan", "net_service_detect", "net_http_probe", "net_tls_check",
         "net_tls_check_bulk", "net_subnet_calc",
         "net_subnet_sweep", "net_route_diagnostics"},

    # SNMP + topologie réseau (v2.155)
    ("snmp", "topologie", "topologie réseau", "schéma réseau", "diagramme réseau",
     "diagramme de topologie", "interfaces du switch", "interfaces du routeur"):
        {"net_snmp_query", "net_topology_diagram"},

    # Fiches de révision / quiz (v2.155)
    ("fiche de révision", "fiches de révision", "quiz", "révise", "réviser", "flashcard",
     "flashcards", "teste-moi", "teste moi", "prépare mon examen", "prépare ma certification",
     "préparer ma certification", "réviser ma certification", "réviser pour"):
        {"quiz_generate", "quiz_next", "quiz_answer", "quiz_stats"},

    # Inventaire matériel
    ("caractéristiques matérielles", "caractéristique matérielle", "specs du pc", "specs pc",
     "spécifications matérielles", "carte mère", "quel processeur", "quelle carte graphique",
     "config du pc", "configuration matérielle", "fiche technique pc", "inventaire matériel",
     "numéro de série", "n° de série", "modèle du pc", "pilotes officiels", "drivers officiels"):
        {"pc_hardware_specs", "win_system_report"},

    # GPU / changement de carte graphique
    ("gpu", "carte graphique", "changé de carte", "changement de carte", "nouvelle carte graphique",
     "j'ai changé de gpu", "quel gpu", "vram", "directml", "carte amd", "carte nvidia",
     "génération vidéo", "video locale", "vidéo locale"):
        {"pc_gpu_status", "pc_hardware_specs"},

    # Apprentissage / introspection des compétences
    ("qu'as-tu appris", "qu'est-ce que tu as appris", "qu'as tu appris", "as-tu appris",
     "historique d'apprentissage", "journal d'apprentissage", "learning log",
     "pourquoi as-tu changé", "pourquoi as tu changé cette compétence", "comment tu t'améliores",
     "apprentissage nocturne", "consolidation nocturne", "que t'a appris cet échec"):
        {"skill_learning_log"},

    # Windows+ (raccourcis panneaux Windows)
    ("god mode", "panneau de configuration", "ouvre les paramètres", "ouvre le gestionnaire de tâches",
     "gestionnaire des tâches", "ouvre services", "services windows", "ouvre le pare-feu",
     "observateur d'événements", "planificateur de tâches", "gestion des disques",
     "gestionnaire de périphériques", "nettoyage de disque", "moniteur de ressources",
     "ouvre le dossier temp", "dossier de démarrage", "programmes et fonctionnalités",
     "connexions réseau", "propriétés système", "msconfig"):
        {"win_quick_launch", "win_quick_launch_list"},

    # SSH
    ("ssh", "serveur distant", "serveur", "ssh connect", "sftp", "transfert fichier",
     "uploader sur le serveur", "télécharger du serveur", "mes serveurs", "parc serveurs"):
        {"ssh_list", "ssh_connection_save", "ssh_exec", "ssh_exec_multi", "ssh_upload", "ssh_download",
         "ssh_list_dir", "ssh_server_info", "ssh_write_and_run"},

    # Drive / OneDrive
    ("drive", "google drive", "onedrive", "cloud"):
        {"google_drive_list", "google_drive_read", "google_drive_upload",
         "onedrive_list", "onedrive_read", "onedrive_upload"},

    # Tâches / notes / mémoire
    ("tâche", "tache", "todo", "à faire", "rappel"):
        {"task_create", "task_list", "task_update", "task_delete"},
    ("note", "noter", "rappel-toi"):
        {"note_create", "note_list", "note_update", "note_delete"},
    ("souvenir", "mémorise", "memorise", "rappelle-toi", "n'oublie pas"):
        {"memory_save", "memory_list", "memory_delete", "memory_search"},

    # Code Python
    ("code workspace", "coding mission", "mission de code", "test forge", "code forge",
     "projet de code", "workspace de code"):
        {"code_workspace_start", "code_workspace_status", "code_workspace_control",
         "ai_code_forge", "ai_test_forge"},
    ("code python", "script python", "execute python", "analyse avec python"):
        {"code_python"},

    # Couleurs
    ("couleur", "color", "hex", "rgb", "hsl"):
        {"color_tool"},

    # QR Code
    ("qr code", "qrcode", "qr"):
        {"qr_generate"},

    # Images
    ("image", "photo", "redimensionne", "resize", "rogne", "rogner", "crop", "recadre",
     "pivote l'image", "tourne l'image", "retourne l'image", "miroir", "flip",
     "compresse l'image", "compresser l'image", "réduis le poids", "allège l'image",
     "par lot", "en lot", "toutes les images", "lot d'images", "dossier d'images",
     "traite les images", "traiter les images", "batch"):
        {"image_info", "image_resize", "image_crop", "image_rotate", "image_compress",
         "image_batch", "images_to_pdf", "ocr_extract"},

    # SQLite / Git / archives
    ("sqlite", "base de données", "requête sql"):
        {"sqlite_query", "sqlite_tables"},
    ("git", "dépôt", "commit", "branche"):
        {"git_info"},
    ("zip", "archive", "extrait"):
        {"file_compress", "file_extract", "zip_list"},

    # Renommage
    ("renomme", "renommer", "renommage en masse"):
        {"file_rename", "bulk_rename"},

    # JSON / regex / texte
    ("json", "formate le json"):
        {"json_tool"},
    ("regex", "expression régulière", "regexp"):
        {"regex_tool"},
    ("markdown",):
        {"markdown_convert"},
    ("compte les mots", "statistiques texte", "longueur du texte"):
        {"text_stats", "text_extract"},

    # Vidéo / infographie
    ("infographie", "graphique"):
        {"infographic_create"},

    # v2.145 — Mini-appli web (« ChatGPT Sites »)
    ("dashboard", "mini-appli", "mini appli", "page web", "interface web",
     "appli web", "application web", "site interactif", "prototype web",
     "page de suivi", "outil interactif", "webapp"):
        {"webapp_create"},

    # Édition vidéo / GIF (v2.32)
    ("vidéo", "video", "gif", "mp4", "avi", "mkv", "mov", "webm",
     "convertis en gif", "convertir en gif", "découpe la vidéo", "decoupe la video",
     "trim", "compresse la vidéo", "compresse la video", "compresser",
     "filigrane", "watermark", "ralenti", "accéléré", "accelere",
     "extrait les images", "extraire les images", "miniature", "thumbnail",
     "enregistre l'écran", "screen record", "capture vidéo", "optimise le gif",
     "redimensionne la vidéo", "vitesse de la vidéo"):
        {"video_info", "video_to_gif", "gif_to_video", "video_trim",
         "video_compress", "video_resize", "video_extract_frames", "video_speed",
         "video_watermark", "gif_optimize", "screen_record_gif",
         "infographic_create", "system_search", "file_find"},

    # Voix
    ("transcription", "transcris", "voix", "whisper", "sous-titre"):
        {"voice_transcribe"},

    # Boîte à outils audio (ffmpeg)
    ("audio", "son", "mp3", "wav", "ogg", "flac", "aac", "m4a", "musique", "piste audio",
     "extrais l'audio", "extraire l'audio", "extrais le son", "convertis l'audio",
     "convertir en mp3", "convertir en wav", "découpe l'audio", "coupe l'audio",
     "fusionne l'audio", "monte le son", "baisse le son", "volume", "normalise l'audio",
     "infos audio", "bitrate", "débit audio"):
        {"audio_info", "audio_extract", "audio_convert", "audio_trim",
         "audio_merge", "audio_volume", "voice_transcribe", "text_to_speech"},

    # Auto-diagnostic
    ("auto-diagnostic", "autodiagnostic", "self test", "self-test", "teste tes outils",
     "vérifie tes outils", "verifie tes outils", "est-ce que tout fonctionne",
     "tout fonctionne", "santé des outils", "diagnostic des outils", "tes fonctions marchent"):
        {"system_self_test"},

    # Devis / Facturation IT (commercial)
    ("devis", "facture", "facturation", "facturer", "proposition commerciale", "client it",
     "tarif", "tarifs", "prix de vente", "marge", "catalogue", "prestation", "prestations",
     "comparer les prix", "comparer les offres", "prix du marché", "prix marché",
     "combien facturer", "combien vendre", "encaissement", "impayé", "impayés",
     "chiffre d'affaires", "mrr", "arr", "tco", "rentabilité", "rentable"):
        {"billing_market_research", "billing_price_recommendation", "billing_generate_proposal",
         "billing_tco_analysis", "billing_invoice_create", "billing_invoice_list",
         "billing_invoice_mark_paid", "billing_revenue_dashboard", "billing_catalog_enrich",
         "billing_analyze_need", "billing_quote_create", "billing_quote_list",
         "billing_client_list", "billing_catalog_list", "billing_tier_breakdown",
         "billing_product_reviews", "billing_seed_trade", "web_search"},

    # Documentation technique IT
    ("documentation", "rapport d'intervention", "rapport intervention", "procédure",
     "runbook", "post-mortem", "postmortem", "cause racine", "rca", "demande de changement",
     "change request", "plan de reprise", "pra", "pca", "fiche client", "schéma réseau",
     "documenter", "compte rendu", "onboarding", "offboarding", "arrivée collaborateur",
     "départ collaborateur", "fiche d'intervention", "maintenance préventive"):
        {"doc_generate_report", "doc_generate_procedure", "doc_generate_runbook",
         "doc_generate_postmortem", "doc_generate_change", "doc_generate_onboarding",
         "doc_generate_recovery_plan", "doc_generate_maintenance", "doc_generate_client_sheet",
         "doc_generate_schema", "doc_analyze_input", "doc_intervention_create",
         "doc_intervention_list", "doc_knowledge_search"},

    # Métier / catalogue par métier (devis utilisable hors IT)
    ("métier", "metier", "plomberie", "plombier", "électricité", "electricien", "électricien",
     "peinture", "peintre", "menuiserie", "menuisier", "jardinage", "paysagiste", "ménage",
     "menage", "coiffure", "esthétique", "photographe", "comptable", "comptabilité",
     "artisan", "btp", "bâtiment", "prestations types", "catalogue métier"):
        {"billing_seed_trade", "billing_catalog_list", "billing_analyze_need",
         "billing_quote_create", "billing_client_create"},

    # Prix d'un produit / achat / budget (le plus important : ne jamais refuser)
    ("prix", "prix de", "les prix", "combien coûte", "combien coute", "ça coûte",
     "ca coute", "coûte combien", "coute combien", "coût de", "cout de", "coût d'",
     "tarif de", "acheter", "achat", "à vendre", "prix moyen", "entrée de gamme",
     "entré de gamme", "milieu de gamme", "haut de gamme", "moins de", "pas cher",
     "le moins cher", "budget", "à partir de", "fourchette de prix", "ça vaut",
     "ca vaut", "ça coûte combien", "pc", "ordinateur", "portable", "laptop",
     "macbook", "serveur", "écran", "imprimante", "disque dur", "ssd", "barrette",
     "carte graphique", "processeur", "switch", "routeur", "nas"):
        {"billing_market_research", "billing_find_products", "billing_product_reviews",
         "billing_price_recommendation", "it_kb_recommend", "web_search"},

    # Avis produits / comparatif
    ("avis", "avis client", "note", "notes", "étoiles", "review", "reviews", "fiable",
     "fiabilité", "réputation", "le meilleur", "lequel choisir", "comparatif", "vaut-il"):
        {"billing_product_reviews", "billing_market_research", "billing_find_products",
         "it_kb_recommend", "web_search"},

    # Base de connaissances IT : recommandation d'outils/logiciels
    ("quel outil", "quel logiciel", "recommande", "recommandation", "conseille", "conseil",
     "antivirus", "sauvegarde", "backup", "supervision", "monitoring", "pare-feu", "firewall",
     "virtualisation", "hyperviseur", "accès distant", "prise en main", "rmm", "edr",
     "gestionnaire de mot de passe", "outil pour", "logiciel pour", "solution pour",
     "diagnostic", "clonage", "imagerie", "scanner réseau", "vpn"):
        {"it_kb_recommend", "it_kb_search", "it_kb_list", "it_kb_add",
         "billing_product_reviews", "web_search"},
}


_strip_accents = _cr.strip_accents


# Index précalculé (normalisé UNE fois au chargement, pas à chaque message) : évite de
# refaire le NFKD sur ~400 mots-clés à chaque tour de chat.
_KEYWORD_TOOLS_NORM = [
    (tuple(_strip_accents(k) for k in keywords), tools)
    for keywords, tools in _KEYWORD_TOOLS.items()
]


async def _filter_relevant_tools(messages: list[dict], profile_name: str) -> list:
    """
    Réduit l'ensemble des outils envoyés au LLM en fonction du message utilisateur.
    → Contexte système plus court → réponse beaucoup plus rapide.

    Stratégie :
    - Toujours inclure les outils universels (mémoire, paths, datetime)
    - Inclure les outils correspondant aux mots-clés du dernier message
    - Si aucun mot-clé match → fallback sur le top 20 (les plus utilisés)
    """
    # Extraire le texte du dernier message utilisateur
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if not last_user:
        return TOOLS_SPEC  # Pas de message → tout envoyer par sécurité

    content = last_user.get("content", "")
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    text_raw = (content or "")
    text = text_raw.lower()
    text_norm = _strip_accents(text)   # « caracteristiques » doit matcher « caractéristiques »

    # 1) Mots-clés (rapide, fiable pour les formulations connues) — insensible aux accents.
    relevant = set(_ALWAYS_INCLUDE)
    keyword_hits = set()
    for keywords, tools in _KEYWORD_TOOLS_NORM:
        if any(k in text_norm for k in keywords):
            keyword_hits.update(tools)
    relevant |= keyword_hits

    # 2) Sémantique + appris (comprend les paraphrases, s'améliore avec l'usage).
    #    Best-effort : si l'embedding/Qdrant échoue, on garde juste les mots-clés.
    semantic = set()
    try:
        import tool_router
        routed = await tool_router.route_tools(text_raw)
        semantic = (routed.get("semantic", set()) | routed.get("learned", set()))
    except Exception:
        pass
    relevant |= semantic

    # 3) Toujours rien de spécifique → repli BORNÉ sur un petit jeu polyvalent.
    #    ⚠️ NE JAMAIS renvoyer les ~245 specs (prompt énorme → réponse très lente).
    if len(relevant) <= len(_ALWAYS_INCLUDE):
        relevant |= _COMMON_TOOLS

    # N'envoyer que des outils RÉELLEMENT existants
    names = {s.get("function", {}).get("name") for s in TOOLS_SPEC}
    relevant &= names

    # 4) Plafond selon le MODE de performance (max_tools) : sur petite machine on envoie peu
    #    d'outils (rapide) ; sur machine puissante, beaucoup (meilleure sélection). On garde
    #    PRIORITAIREMENT l'essentiel + les correspondances mots-clés, puis on complète.
    # v2.107 — le profil analysis envoyait TOUS les outils (~294) sans filtrage : sur un
    # catalogue aussi large, le LLM peut halluciner un nom d'outil plausible mais inexistant
    # au lieu d'utiliser le bon (constaté : "HWMonitor" inventé au lieu de pc_hardware_specs).
    # On applique désormais le même filtrage mots-clés+sémantique que chat/agent, mais avec
    # un plafond bien plus large (le profil analysis pairé à un modèle puissant peut gérer
    # plus de contexte) — garde la qualité/couverture tout en réduisant le bruit du catalogue.
    try:
        max_tools = int(db.get_setting("max_tools") or 28)
    except Exception:
        max_tools = 28
    if profile_name == "analysis":
        max_tools = max(max_tools, 90)
    if len(relevant) > max_tools:
        ordered = []
        for group in (set(_ALWAYS_INCLUDE) & names, keyword_hits & names, semantic & names, relevant):
            for t in group:
                if t in relevant and t not in ordered:
                    ordered.append(t)
        relevant = set(ordered[:max_tools])

    return [s for s in TOOLS_SPEC if s.get("function", {}).get("name") in relevant]


async def _smart_title_upgrade(conversation_id: str, user_text: str):
    """v2.171 — titre plus soigné qu'une simple troncature, généré en arrière-plan (ne
    bloque jamais l'envoi). Passe par _ollama_generate (tools.py), donc bénéficie
    automatiquement du même routage cloud/sensibilité que tout appel LLM interne (v2.122) —
    si le message contient un mot-clé sensible, l'appel reste local comme n'importe où
    ailleurs, sans logique dupliquée ici."""
    try:
        import tools as _tm
        prompt = (
            "Résume cette demande en un titre TRÈS court (3 à 5 mots), en français, sans "
            "guillemets ni point final, comme un titre d'onglet de navigateur. Réponds "
            "UNIQUEMENT le titre, rien d'autre.\n\nDemande : " + user_text[:500]
        )
        raw = await _tm._ollama_generate(prompt, timeout=25)
        title = (raw or "").strip().strip('"“”«»').split("\n")[0].strip(" .")[:60]
        if title:
            db.upgrade_conversation_title_silent(conversation_id, title)
    except Exception:
        pass


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


async def _critique_action(user_query: str, tool_name: str, args: dict, model: str = None):
    """Auto-critique : vérifie qu'une action sensible correspond bien à la demande.
    Renvoie None si OK, sinon une courte phrase décrivant le souci. Best-effort.
    Réutilise le modèle déjà chargé (model) pour éviter de charger un 2ᵉ modèle."""
    try:
        import tools as _tm
        prompt = (
            "Tu es un contrôleur de sécurité. Tu dois détecter si une action ne correspond PAS à la demande.\n\n"
            f"DEMANDE : « {user_query} »\n"
            f"ACTION PRÉVUE : {tool_name} avec {json.dumps(args, ensure_ascii=False)[:400]}\n\n"
            "Le TYPE d'action et ses cibles correspondent-ils à la demande ?\n"
            "- Si l'action fait clairement autre chose que demandé (ex: la demande parle de supprimer une tâche "
            "mais l'action envoie un email), réponds : PROBLEME: <quoi> en UNE phrase.\n"
            "- Si l'action correspond bien à la demande, réponds uniquement : OK\n"
            "Réponse :"
        )
        r = (await _tm._ollama_generate(prompt, model=model, timeout=60) or "").strip()
        if not r or r.upper().startswith("OK") or len(r) < 5:
            return None
        r = r.split("\n")[0]
        r = re.sub(r"^\s*PROBL[EÈ]?ME\s*:\s*", "", r, flags=re.IGNORECASE)
        return r[:200] if len(r) >= 5 else None
    except Exception:
        return None


async def _conversation_summary(conversation_id: str, overflow: list, model: str = None) -> str | None:
    """Compaction (anti « context rot ») : résume les messages ANCIENS sortis de la fenêtre
    de contexte, au lieu de les perdre. Mis en cache par conversation et régénéré seulement
    tous les ~6 messages (sinon on réutilise le résumé). Utilise le modèle déjà chargé."""
    if not overflow or len(overflow) < 4:
        return None
    cached = None
    if conversation_id:
        try:
            cached = db.get_setting(f"convsum_{conversation_id}")
        except Exception:
            cached = None
    if isinstance(cached, dict) and cached.get("summary") and abs(cached.get("covered", 0) - len(overflow)) < 6:
        return cached["summary"]
    parts = []
    for m in overflow[-40:]:
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        if c and m.get("role") in ("user", "assistant"):
            who = "Utilisateur" if m.get("role") == "user" else "Marvin"
            parts.append(f"{who}: {str(c)[:500]}")
    if not parts:
        return None
    prompt = ("Résume cette conversation en quelques puces FACTUELLES et utiles (décisions prises, "
              "informations importantes, préférences exprimées, tâches/sujets en cours) afin de garder "
              "le contexte. Sois bref et concret.\n\n" + "\n".join(parts) + "\n\nRÉSUMÉ :")
    try:
        import tools as _tm
        s = (await _tm._ollama_generate(prompt, model=model, timeout=120) or "").strip()
    except Exception:
        return cached.get("summary") if isinstance(cached, dict) else None
    if s and conversation_id:
        try:
            db.set_setting(f"convsum_{conversation_id}", {"covered": len(overflow), "summary": s[:1500]})
        except Exception:
            pass
    return s[:1500] if s else None


# ── Agent de streaming principal ──────────────────────────────────────────────

def _is_tooling_failure(result) -> bool:
    """Vrai si le résultat d'un outil traduit un PROBLÈME DE COMPÉTENCE/OUTILLAGE
    (mauvais outil, mauvaise commande/shell, paramètre invalide, outil inconnu) — et
    PAS un simple résultat réel négatif (ex. ping vers un hôte éteint). Sert à décider
    s'il faut auto-réparer la compétence, sans dégrader une compétence qui marche."""
    if not isinstance(result, dict):
        return False
    # Erreurs ENVIRONNEMENTALES (non corrigeables en réécrivant la compétence) → ignorées :
    # timeout (commande lente), droits admin/permission, antivirus. Évite les faux upgrades.
    _blob_env = (str(result.get("error", "")) + " " + str(result.get("stderr", "")) + " "
                 + str(result.get("message", ""))).lower()
    _env_sigs = (
        # environnement (non corrigeable par une réécriture de compétence)
        "délai dépassé", "delai depasse", "timed out", "timeout", "accès refusé",
        "acces refuse", "access denied", "administrateur", "antivirus", "permission refusée",
        # entrée utilisateur manquante (≠ défaut de compétence) → ne pas auto-upgrader
        "requis", "required", "manquant", "missing", "fournis", "préciser", "preciser",
        "renseigner", "obligatoire")
    if any(s in _blob_env for s in _env_sigs):
        return False
    if result.get("error"):
        return True
    if result.get("success") is False:
        blob = (str(result.get("stderr", "")) + " " + str(result.get("stdout", ""))).lower()
        sigs = ("is not recognized", "n'est pas reconnu", "not recognized as",
                "commandnotfound", "cmdletnotfound", "the term ", "parsererror",
                "unexpected token", "paramètre", "parameterbinding", "cannot be loaded",
                "outil inconnu", "argument", "syntax")
        return any(s in blob for s in sigs)
    return False


def _salvage_text_tool_calls(content: str, allowed_names: set) -> list:
    """
    Filet de sécurité : certains modèles (qwen2.5 notamment, surtout quand une
    compétence injecte une méthode pas-à-pas) DÉCRIVENT les appels d'outils en
    TEXTE/JSON (souvent dans un bloc ```json {"name":..., "arguments":...} ```)
    au lieu de les émettre nativement → aucun outil ne s'exécute, Marvin « parle »
    au lieu d'« agir ». Cette fonction récupère ces appels pour les EXÉCUTER vraiment.

    Sécurité : on ne récupère QUE des outils réellement proposés ce tour-ci
    (allowed_names) ; les permissions sont vérifiées ensuite par le chemin normal.
    Retourne une liste au format natif : [{"function": {"name", "arguments"}}].
    """
    if not content or not allowed_names:
        return []

    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    _norm_map = {}
    for a in allowed_names:
        _norm_map.setdefault(_norm(a), a)

    def _resolve(name: str):
        """Résout un nom d'outil (éventuellement halluciné) vers un outil réel autorisé."""
        if not name:
            return None
        if name in allowed_names:
            return name
        nn = _norm(name)
        if nn in _norm_map:                      # même nom à la casse/ponctuation près
            return _norm_map[nn]
        # sous-chaîne UNIQUE (ex. 'ping' → 'net_ping', 'process kill' → 'pc_process_kill')
        cands = [real for nrm, real in _norm_map.items() if nn and (nn in nrm or nrm in nn)]
        return cands[0] if len(set(cands)) == 1 else None

    dec = json.JSONDecoder()
    calls, seen = [], set()
    i, n = 0, len(content)
    while i < n:
        if content[i] != "{":
            i += 1
            continue
        try:
            obj, end = dec.raw_decode(content, i)   # gère les accolades imbriquées
        except Exception:
            i += 1
            continue
        i = end
        if not isinstance(obj, dict):
            continue
        fn = obj.get("function") if isinstance(obj.get("function"), dict) else {}
        name = _resolve(obj.get("name") or obj.get("tool") or fn.get("name"))
        args = obj.get("arguments")
        if args is None:
            args = obj.get("parameters") or obj.get("args") or fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if not name or name not in allowed_names or not isinstance(args, dict):
            continue
        key = name + json.dumps(args, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        calls.append({"function": {"name": name, "arguments": args}})

    # 2ᵉ passe — nom AVANT l'accolade : `net_ping {"host":...}`, `net_ping({...})`,
    # ou bloc ```net_ping\n{...}```. Fréquent avec le petit modèle chat (3b).
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]{2,40})\s*\(?\s*(\{)", content):
        real = _resolve(m.group(1))
        if not real or real not in allowed_names:
            continue
        try:
            obj, _ = dec.raw_decode(content, m.start(2))   # l'objet APRÈS le nom = les arguments
        except Exception:
            continue
        # ignorer une enveloppe d'appel déjà gérée par la passe 1 ({name/function/arguments})
        if not isinstance(obj, dict) or any(k in obj for k in ("name", "function", "arguments")):
            continue
        key = real + json.dumps(obj, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        calls.append({"function": {"name": real, "arguments": obj}})
    return calls


# v2.175 — jusqu'ici, une image attachée au chat n'était utilisée QUE pour ce tour (vision
# ponctuelle) puis jetée : agent.py extrayait le texte du message multimodal et écrivait
# `content` seul en base, sans jamais toucher les images (cf. mémoire document-identity-toc-v2174
# et le pipeline documenté à l'époque de l'ajout du multi-attach v2.140). Pour « ingurgiter
# beaucoup de captures et en faire de la documentation », il faut d'abord qu'elles SURVIVENT
# au tour — persistées sur disque + analysées une fois (légende + texte relevé) + indexées
# dans la table `screenshots`, pour qu'un outil ultérieur (doc_generate_from_screenshots)
# puisse les récupérer sans jamais renvoyer les octets bruts au modèle à chaque nouveau tour.
_MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
             "image/gif": ".gif", "image/webp": ".webp"}


async def _persist_and_analyze_one_screenshot(conversation_id: str, data_url: str) -> dict | None:
    try:
        header, b64data = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "") if ":" in header else "image/png"
        ext = _MIME_EXT.get(mime, ".png")
        raw = base64.b64decode(b64data)

        conv_dir = DATA_DIR / "screenshots" / conversation_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}{ext}"
        fpath = conv_dir / fname
        fpath.write_bytes(raw)

        analysis = await _tools_mod._analyze_screenshot(str(fpath))
        row = db.create_screenshot(conversation_id, str(fpath),
                                    analysis.get("caption", ""), analysis.get("ocr_text", ""))
        return row
    except Exception:
        return None


async def _persist_and_analyze_screenshots(conversation_id: str, content_parts: list) -> list[dict]:
    """Best-effort, jamais bloquant pour le tour : une erreur d'analyse d'UNE capture ne doit
    pas empêcher le reste de la conversation. Traitées en parallèle (asyncio.gather) — avec
    plusieurs captures, les analyser en série aurait ajouté plusieurs x le temps d'un appel
    vision (~6s en cloud, jusqu'à 90s en repli local) au tour en cours."""
    urls = []
    for part in content_parts or []:
        if isinstance(part, dict) and part.get("type") in ("image_url", "image"):
            url = part.get("image_url", {}).get("url", "") or part.get("url", "")
            if url.startswith("data:"):
                urls.append(url)
    if not urls:
        return []
    results = await asyncio.gather(
        *[_persist_and_analyze_one_screenshot(conversation_id, u) for u in urls],
        return_exceptions=False,
    )
    return [r for r in results if r]


async def run_agent(
    messages: list[dict],
    conversation_id: str | None,
    model: str | None,
    cortex_contract: dict | None = None,
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
    # ── Créer ou récupérer la conversation ───────────────────────────────────
    if not conversation_id:
        conv = db.create_conversation("Nouvelle conversation")
        conversation_id = conv["id"]
        yield _sse({"type": "conv_id", "conversationId": conversation_id})

    # ── Sauvegarder le dernier message utilisateur ────────────────────────────
    last_msg = messages[-1] if messages else None
    _user_query = ""   # texte de la demande utilisateur (pour l'apprentissage du routing)
    if last_msg and last_msg.get("role") == "user":
        content = ""
        if isinstance(last_msg.get("content"), str):
            content = last_msg["content"]
        elif isinstance(last_msg.get("content"), list):
            # Multimodal — extract text only for DB storage
            content = " ".join(
                p.get("text", "") for p in last_msg["content"] if p.get("type") == "text"
            ).strip()
        elif isinstance(last_msg.get("parts"), list):
            content = "".join(
                p.get("text", "") for p in last_msg["parts"] if p.get("type") == "text"
            )
        db.create_message(conversation_id, "user", content)
        _user_query = content

        # v2.175 — persiste + analyse (légende + texte relevé) toute image jointe à CE message,
        # avant qu'elle ne soit perdue (jusqu'ici jamais sauvegardée au-delà du tour courant).
        if isinstance(last_msg.get("content"), list):
            try:
                _saved_shots = await _persist_and_analyze_screenshots(conversation_id, last_msg["content"])
                if _saved_shots:
                    yield _sse({"type": "screenshots_saved", "count": len(_saved_shots)})
            except Exception:
                pass
        # v2.170 — titrer la conversation IMMÉDIATEMENT depuis le message utilisateur,
        # avant même que l'assistant réponde. Avant ce correctif, le titre n'était posé
        # qu'après une réponse COMPLÈTE (voir plus bas) — si le tour était interrompu en
        # route (flux abandonné, MAX_TOOL_STEPS, crash...) la conversation restait
        # "Nouvelle conversation" pour toujours. Signalé par l'utilisateur (capture d'écran
        # de la barre latérale — une grande partie des entrées jamais titrées). Indépendant
        # de la réussite du tour, comme chez Claude/ChatGPT (le titre apparaît dès l'envoi).
        try:
            conv = db.get_conversation(conversation_id)
            if conv and conv.get("title") == "Nouvelle conversation" and content.strip():
                db.update_conversation_title(conversation_id, _autotitle_from_text(content))
                # v2.171 — titre intelligent (LLM léger) en arrière-plan, sans jamais
                # retarder l'envoi : la troncature ci-dessus s'affiche tout de suite,
                # remplacée par un titre plus soigné quelques secondes après.
                _tt = asyncio.create_task(_smart_title_upgrade(conversation_id, content))
                _BG_LEARN_TASKS.add(_tt)
                _tt.add_done_callback(_BG_LEARN_TASKS.discard)
        except Exception:
            pass
    # Outil(s) cité(s) explicitement par leur nom exact → imposés ce tour-ci, pas de substitution.
    _explicit_tool_names = _exact_tool_mentions_from_text(_user_query)
    # v2.185 — « donne-moi la commande » sans verbe d'exécution → outils d'exécution bloqués ce tour.
    _command_text_only = _wants_command_text_only(_user_query)
    # v2.190 — décisions déterministes AVANT le LLM. Une interdiction explicite, une
    # réponse de quiz ou une création de questionnaire attendue dans le chat ne doivent
    # proposer aucun outil, même si des mots comme « backup » ressemblent à une action.
    _tool_suppression = tool_suppression_reason(messages, _user_query)
    _required_tool_names = (
        {"ai_model_council"}
        if not _tool_suppression and wants_model_council(_user_query)
        else set()
    )
    _workspace_norm = _strip_accents((_user_query or "").casefold())
    _workspace_route = None if _tool_suppression else workspace_followup(messages, _user_query)
    _workspace_mission_id = str((_workspace_route or {}).get("mission_id") or "")
    _workspace_action = str((_workspace_route or {}).get("action") or "resume")
    if _workspace_route:
        _required_tool_names.add(_workspace_route["tool"])

    # v2.224 — Cortex compile les six axes en contrat explicable. Auto reste sans outil
    # sauf demande explicitement approfondie et complexe, non sensible, qui peut imposer
    # l'équipe adaptative de lecture/recherche. Les interdictions déterministes gagnent.
    import cortex as _cortex
    _cortex_plan = _cortex.compile_contract(_user_query, cortex_contract)
    if not _tool_suppression:
        _required_tool_names.update(_cortex_plan.get("forced_tools") or [])
    if "code_workspace_control" in _required_tool_names:
        # Une réparation d'une mission existante doit reprendre son snapshot. Relancer
        # ai_code_forge ou créer une nouvelle mission ferait perdre l'état et les preuves.
        _required_tool_names.discard("ai_code_forge")
        _required_tool_names.discard("code_workspace_start")
    yield _sse({"type": "cortex_contract", "contract": _cortex_plan})

    # v2.120 — Mode « Hyper sécurisé » : coupe-circuit lu UNE fois, prioritaire sur tout
    # (auto-routing cloud ci-dessous ET sélection manuelle d'un modèle cloud).
    _lockdown = _is_local_only_lockdown()
    # v2.121 — Mode « Ultra débridé » : désactive SEULEMENT la détection de sensibilité
    # (choix de confidentialité assumé par l'utilisateur), jamais le garde-fou système de
    # security.py. _lockdown reste prioritaire si jamais les deux étaient actifs ensemble
    # (ne devrait pas arriver via l'UI, les presets sont mutuellement exclusifs, mais un
    # verrou de sécurité doit toujours gagner par défense en profondeur).
    _ultra = (not _lockdown) and _is_ultra_unrestricted()

    # ── Sélection intelligente du modèle ─────────────────────────────────────
    if not model or model == "auto":
        # Mode automatique : détecter le profil optimal
        await _refresh_model_cache()
        profile_name, active_model, temperature = _detect_profile(messages)
        # v2.119 — Ollama Cloud (opt-in, désactivé par défaut) : bascule vers un modèle
        # cloud SEULEMENT si ce tour ne touche aucune donnée sensible (cf. commentaire sur
        # _SENSITIVE_TOOL_PREFIXES plus haut) — SAUF en mode Ultra débridé (v2.121), qui
        # ignore délibérément cette vérification. Un choix de modèle MANUEL par l'utilisateur
        # (branche else ci-dessous) n'est jamais réécrit ici — seule la protection mid-boucle
        # plus bas s'applique alors, en dernier recours.
        _cloud_enabled, _cloud_overrides = _get_cloud_config()
        if _cloud_enabled and not _lockdown and profile_name in _cloud_overrides:
            _text_norm = _strip_accents((_user_query or "").lower())
            if _ultra or not _is_sensitive_request(messages, _text_norm):
                configured_cloud = _cloud_overrides[profile_name]
                installed_cloud = _cr.list_installed_cloud_models()
                active_model = (
                    configured_cloud if configured_cloud in installed_cloud
                    else (_cr.pick_best_cloud_model("general") or active_model)
                )
                # v2.141/v2.179 — routage par TÂCHE prioritaire sur le routage par PROFIL : un
                # signal clair (ex. demande de script/procédure) route vers le modèle
                # cloud le plus fort en code plutôt que le généraliste agentique du
                # profil. Résolu EN DIRECT sur les modèles installés (pick_best_cloud_model),
                # plus jamais via un tag figé dans un réglage — un modèle cloud peut être
                # retiré par le fournisseur en quelques jours (constaté en réel, v2.179).
                _task = _cr.detect_task(_user_query)
                if _task:
                    _picked = _cr.pick_best_cloud_model(_task)
                    if _picked:
                        active_model = _picked
    else:
        # Modèle forcé manuellement par l'utilisateur
        active_model = model
        profile_name = "manual"
        # v2.120 — même un choix manuel explicite de modèle cloud est bloqué en Hyper
        # sécurisé : ce mode est un vrai coupe-circuit, pas une simple valeur par défaut.
        if _lockdown and _is_cloud_model(active_model):
            active_model = (
                MODEL_PROFILES.get("agent", {}).get("model")
                or DEFAULT_MODEL
            )
            profile_name = "agent"
        # Température basse = tool-calling déterministe, zéro hallucination (même doctrine
        # que MODEL_PROFILES ci-dessus — v2.106 : cette branche faisait l'INVERSE, montait
        # à 0.6 pour les PETITS modèles alors que ce sont eux les plus sujets à halluciner
        # un nom d'outil/paramètre plausible mais faux — voir ocr_extract "llava:13b" jamais
        # installé, trouvé lors de l'audit des échecs réels).
        if any(x in active_model for x in (":3b", ":1b", ":2b", "3b", "1b")):
            temperature = 0.3
        elif any(x in active_model for x in (":7b", ":8b", "7b", "8b")):
            temperature = 0.2
        elif any(x in active_model for x in (":14b", ":13b", ":12b", "14b")):
            temperature = 0.2
        else:
            temperature = 0.3

    # Ultra débridé est désormais un contrat cloud-only pour tout LLM génératif.
    # Il couvre aussi les profils sans override (vision), un modèle local choisi
    # manuellement et un override cloud retiré. Aucun repli local silencieux.
    if _ultra:
        _cloud_need = (
            "vision" if profile_name == "vision"
            else (_cr.detect_task(_user_query) or {
                "analysis": "reasoning", "agent": "agentic",
            }.get(profile_name, "general"))
        )
        try:
            active_model = _cr.require_cloud_model(
                _cloud_need,
                requested_model=active_model if _is_cloud_model(active_model) else None,
            )
        except _cr.CloudOnlyModelUnavailable as exc:
            yield _sse({"type": "error", "message": str(exc), "cloud_only": True})
            return

    # Local strict est un choix par message, prioritaire sur le routage cloud mais
    # sans modifier le preset global de la machine. Ultra cloud-only gagne sur ce
    # réglage conversationnel afin que son comportement ne soit jamais ambigu.
    _cortex_privacy = _cortex_plan["resolved"]["privacy"]
    _cortex_sensitive = _is_sensitive_request(
        messages, _strip_accents((_user_query or "").lower())
    )
    if (
        not _ultra
        and _is_cloud_model(active_model)
        and (_cortex_privacy == "local" or (_cortex_privacy == "hybrid_redacted" and _cortex_sensitive))
    ):
        active_model = (
            MODEL_PROFILES.get(profile_name, {}).get("model")
            or MODEL_PROFILES.get("agent", {}).get("model")
            or DEFAULT_MODEL
        )
        if profile_name == "manual":
            profile_name = "agent"

    # v2.119 — modèle local de repli si le modèle courant est un modèle cloud et qu'un
    # outil sensible est appelé EN COURS de boucle (ex. l'agent décide d'appeler email_read
    # sans que "email" n'apparaisse dans le message initial) : bascule immédiate AVANT que
    # le résultat (contenu d'email, sortie SSH…) ne soit envoyé au modèle cloud au tour
    # suivant. S'applique même en sélection manuelle d'un modèle cloud (profile_name
    # "manual") — c'est une protection de dernier recours, pas une simple commodité.
    _local_fallback_model = (
        MODEL_PROFILES.get(profile_name, {}).get("model")
        or MODEL_PROFILES.get("agent", {}).get("model")
        or DEFAULT_MODEL
    )

    # Informer le frontend du modèle sélectionné
    profile_label = MODEL_PROFILES.get(profile_name, {}).get("label", f"🎯 {active_model}")
    if _ultra:
        profile_label = f"☁️ Cloud strict · {active_model}"
    yield _sse({
        "type":    "model_info",
        "profile": profile_name,
        "model":   active_model,
        "label":   profile_label if profile_name != "manual" else f"🎯 {active_model}",
    })

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
    _executed_tool_names: set[str] = set()

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

    # Create ONE shared client for all tool-loop iterations (avoids TCP reconnect per step)
    # Timeout: 300s total (5min) to handle slow first-load on cold models
    # Read timeout: separate so initial connection is fast but reading can be long
    _ollama_timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)

    # NB : on NE force PAS num_ctx ici. Tester un num_ctx réduit (16K) a provoqué un RECHARGEMENT
    # du modèle à chaque message (Ollama indexe l'instance par (modèle, num_ctx) : le prewarm et
    # le « professeur » d'arrière-plan utilisent le défaut → conflit → thrash → 40s/message).
    # Le vrai gain (≈60s→16s) vient du professeur qui réutilise le modèle déjà chargé.
    # top_p resserre l'échantillonnage aux tokens les plus probables (complète la température
    # basse) : réduit le risque que le modèle « invente » un nom d'outil/paramètre plausible
    # mais faux plutôt que de rester sur ce qu'il connaît réellement (v2.106, anti-hallucination).
    _ollama_options = {"temperature": temperature, "top_p": 0.9}

    # Anti-« le modèle explique au lieu d'agir » : on ne le corrige qu'UNE fois.
    _nudged = False

    # Suivi de l'exécution (pour l'auto-réparation des compétences) :
    # nb d'outils OK / en erreur + trace compacte, exploités à la fin si une compétence est active.
    _run_ok = 0
    _run_err = 0
    _run_trace: list = []
    _run_calls: list = []      # séquence structurée [{tool, args}] des appels RÉUSSIS (golden path)
    _read_call_signatures: set[str] = set()
    _blocking_outcomes: dict[str, dict] = {}
    _outcome_recorded = False
    # v2.138 — compensation de la fiabilité composée : la littérature 2026 sur les agents LLM
    # documente qu'à 95% de fiabilité PAR appel, une chaîne de 8 outils ne réussit globalement
    # qu'à ~66% (les erreurs se composent). Pas de changement de comportement ici — juste une
    # trace visible (audit.jsonl) dès qu'un tour dépasse 8 appels, pour que ce signal soit
    # repérable lors d'un futur audit sans avoir à recompter manuellement les tool_start comme
    # fait à la main pour le diagnostic v2.136.
    _long_chain_logged = False

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
            _executed = _run_ok + _run_err
            _ok = (_run_err == 0)
            _detail = f"{_run_err} erreur(s) d'outil sur {_executed} appel(s)."
            _trace = ("Demande: " + (_user_query or "")[:300] + "\n"
                      + "\n".join(_run_trace[-14:])
                      + "\nRéponse finale: " + (full_content or "")[:400])
            _sk.record_outcome(_skill["name"], _ok, _detail, transcript=_trace)
            # 🥇 Succès propre avec au moins un outil → mémoriser le déroulé gagnant
            # (golden path) ; skills garde le plus COURT → la compétence devient + efficace.
            if _ok and _run_ok > 0 and _run_calls:
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

    async with httpx.AsyncClient(timeout=_ollama_timeout) as _ollama_client:
      for step in range(MAX_TOOL_STEPS):
        full_content = ""
        tool_calls_found: list[dict] = []

        try:
            async with _ollama_client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model":   active_model,
                        "system":  system_prompt,
                        "messages": ollama_msgs,
                        "tools":   tools_payload,
                        "stream":  True,
                        "options": _ollama_options,
                        # keep_alive: keeps the model in VRAM/RAM for 30 minutes after
                        # the request finishes → no more cold-load on subsequent messages.
                        # This is the #1 fix for the "Ollama timeout" issue.
                        "keep_alive": "30m",
                    },
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield _sse({"type": "error", "message": f"Ollama HTTP {resp.status_code}: {body.decode()[:200]}"})
                        return

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        msg_part = chunk.get("message", {})
                        token = msg_part.get("content", "")

                        # v2.125 — certains modèles (notamment des modèles cloud "raisonneurs")
                        # renvoient leur raisonnement dans un champ `thinking` SÉPARÉ de
                        # `content`, avant la réponse/l'appel d'outil réel. Ce champ était
                        # jusqu'ici totalement ignoré : l'utilisateur ne voyait RIEN défiler
                        # pendant potentiellement plusieurs dizaines de secondes à plusieurs
                        # minutes (jusqu'à 3min10 mesurées sur des conversations réelles),
                        # ce qui donnait l'impression que Marvin restait bloqué à "réfléchir"
                        # et poussait à annuler manuellement. On le relaie maintenant au
                        # frontend comme un événement dédié (jamais mémorisé dans
                        # full_content — ce n'est pas la réponse finale).
                        thinking_token = msg_part.get("thinking", "")
                        if thinking_token:
                            yield _sse({"type": "thinking", "text": thinking_token})

                        # Stream text tokens to frontend
                        if token:
                            full_content += token
                            if not _blocking_outcomes:
                                yield _sse({"type": "text", "text": token})

                        # Tool calls arrive on the final chunk
                        if msg_part.get("tool_calls"):
                            tool_calls_found = msg_part["tool_calls"]

                        if chunk.get("done"):
                            break

        except httpx.ConnectError:
            yield _sse({"type": "error", "message": f"ConnectError: Impossible de contacter Ollama sur {OLLAMA_URL}. Relancez Marvin avec start.bat."})
            return
        except httpx.ReadTimeout:
            yield _sse({"type": "error", "message": f"Délai d'attente dépassé (300s). Le modèle '{active_model}' est peut-être en train de charger en RAM (~30-60s la 1ère fois). Réessayez dans quelques secondes."})
            return
        except httpx.RemoteProtocolError as e:
            yield _sse({"type": "error", "message": f"RemoteProtocolError: La connexion au modèle '{active_model}' a été coupée. Le modèle a probablement manqué de mémoire. Essayez un modèle plus léger (qwen2.5:3b) ou augmentez le swap Windows."})
            return
        except Exception as e:
            # Build a meaningful error message even if str(e) is empty
            err_msg = str(e).strip()
            err_type = type(e).__name__
            if not err_msg:
                err_msg = f"Exception {err_type} sans message (le modèle {active_model} a peut-être planté ou Ollama a coupé la connexion)"
            else:
                err_msg = f"{err_type}: {err_msg}"
            import traceback as _tb
            yield _sse({
                "type": "error",
                "message": err_msg,
                "detail": _tb.format_exc()[-500:],
                "model": active_model,
            })
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
        _missing_required = _required_tool_names - _executed_tool_names - {
            tc.get("function", {}).get("name", "") for tc in tool_calls_found
        }
        if _missing_required and (not tool_calls_found or step >= MAX_TOOL_STEPS - 2):
            for required_name in sorted(_missing_required):
                if required_name == "ai_model_council":
                    arguments = {"question": _user_query}
                elif required_name == "ai_cortex_search":
                    arguments = {"question": _user_query}
                elif required_name == "ai_research_swarm":
                    arguments = {"question": _user_query}
                elif required_name == "ai_adaptive_team":
                    arguments = {"question": _user_query}
                elif required_name == "ai_code_forge":
                    arguments = {"request": _user_query}
                elif required_name == "code_workspace_start":
                    contextual_request = _user_query
                    if re.search(r"\b(?:ce|le|la)\s+(?:script|code|programme|projet)\b", _workspace_norm):
                        previous_assistant = next(
                            (str(item.get("content") or "") for item in reversed(messages[:-1])
                             if item.get("role") == "assistant" and str(item.get("content") or "").strip()),
                            "",
                        )
                        if previous_assistant:
                            contextual_request += "\n\nContexte du livrable précédent à reprendre :\n" + previous_assistant[-16_000:]
                    arguments = {"request": contextual_request}
                elif required_name == "code_workspace_status":
                    arguments = {"mission_id": _workspace_mission_id}
                elif required_name == "code_workspace_control":
                    arguments = {
                        "mission_id": _workspace_mission_id,
                        "action": _workspace_action,
                    }
                elif required_name in {"web_research", "web_deep_research"}:
                    arguments = {"query": _user_query}
                elif required_name == "long_task_start":
                    arguments = {"goal": _user_query}
                elif required_name == "document_generate":
                    arguments = {"text": _user_query, "template": "libre"}
                else:
                    arguments = {}
                tool_calls_found.append({
                    "id": f"required-{uuid.uuid4().hex[:12]}",
                    "function": {"name": required_name, "arguments": arguments},
                })
            if full_content.strip():
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
                tool_name = tc["function"]["name"]
                tool_args = tc["function"].get("arguments", {})
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except Exception:
                        tool_args = {}
                # Compatibilité avec les erreurs réellement observées dans les conversations :
                # certains modèles utilisent `command` pour pc_run_powershell et l'ancien nom
                # plausible `ssh_connect`. Normaliser avant validation évite un échec inutile.
                if tool_name == "pc_run_powershell" and not tool_args.get("script") and tool_args.get("command"):
                    tool_args["script"] = tool_args.pop("command")
                if tool_name == "ssh_connect" and tool_args.get("save"):
                    tool_name = "ssh_connection_save"
                    tc["function"]["name"] = tool_name
                    tc_db["toolName"] = tool_name
                    tool_args.pop("save", None)

                _read_signature = ""
                if tool_name == "code_workspace_status":
                    _read_signature = json.dumps(
                        {"tool": tool_name, "mission_id": str(tool_args.get("mission_id") or "")},
                        sort_keys=True,
                    )

                tool_call_id = tc_db["toolCallId"]

                # Notifier le frontend — début d'outil
                yield _sse({
                    "type": "tool_start",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "args": tool_args,
                })

                _tool_t0 = time.time()
                # v2.145 — `long_task_start` a besoin du `conversation_id` COURANT pour
                # programmer sa reprise en arrière-plan (cron → nouveau tour sur CETTE
                # conversation) — injecté ici plutôt que demandé au LLM (qui n'a de toute
                # façon pas une vision fiable de son propre conversation_id).
                if tool_name == "long_task_start":
                    tool_args["_conversation_id"] = conversation_id
                if tool_name == "code_workspace_start":
                    tool_args["_conversation_id"] = conversation_id
                # v2.175 — même principe : le modèle n'a pas de vision fiable de son propre
                # conversation_id (règle d'or #7, jamais d'ID inventé) — injecté ici pour les
                # outils qui portent sur "cette conversation" par défaut.
                if tool_name in ("screenshot_list", "doc_generate_from_screenshots") and "conversation_id" not in tool_args:
                    tool_args["_conversation_id"] = conversation_id
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
                    executor = TOOLS_REGISTRY.get(tool_name)
                    if executor:
                        try:
                            result = await executor(tool_args)
                        except Exception as ex:
                            result = _log_tool_exception(tool_name, tool_args, ex, conversation_id)
                    else:
                        result = {"error": f"Outil inconnu : {tool_name}"}

                else:
                    # Niveau Standard (ou non défini) : comportement normal
                    executor = TOOLS_REGISTRY.get(tool_name)
                    if executor:
                        try:
                            result = await executor(tool_args)
                        except Exception as ex:
                            result = _log_tool_exception(tool_name, tool_args, ex, conversation_id)
                    else:
                        result = {"error": f"Outil inconnu : {tool_name}"}

                # v2.248 — contrat additif commun à tous les outils. Les champs historiques
                # restent intacts; `_contract` fournit un état, un code d'erreur et la
                # retryabilité lisibles de façon déterministe par le Chat et les superviseurs.
                if isinstance(result, dict):
                    try:
                        import engineering_runtime as _engineering_runtime
                        result = _engineering_runtime.normalize_tool_result(
                            tool_name, result, duration_ms=int((time.time() - _tool_t0) * 1000),
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
                if tool_name == "ai_test_forge":
                    if isinstance(result, dict) and result.get("success") is True and result.get("production_ready") is True:
                        _blocking_outcomes.pop(tool_name, None)
                    else:
                        _blocking_outcomes[tool_name] = result if isinstance(result, dict) else {"error": str(result)}
                elif tool_name == "ai_code_forge":
                    if isinstance(result, dict) and result.get("success") is True:
                        _blocking_outcomes.pop(tool_name, None)
                    else:
                        _blocking_outcomes[tool_name] = result if isinstance(result, dict) else {"error": str(result)}

                # Journal d'audit : trace l'action (best-effort, n'échoue jamais)
                try:
                    import audit
                    audit.log_action(tool_name, tool_args, result, source="chat")
                except Exception:
                    pass

                # v2.139 — trouvé en implémentant la traçabilité par conversation : la boucle de
                # chat n'écrivait JAMAIS dans `tool_executions` (seuls /api/tools, cron, ssh_exec
                # REST et email_send le faisaient) — le tableau de bord de fiabilité v2.138 ne
                # voyait donc qu'une fraction du vrai usage (les appels pilotés par le LLM, la
                # majorité en pratique, étaient invisibles). Corrigé + conversation_id pour
                # reconstituer la chronologie complète d'un tour (`pc_conversation_trace`).
                try:
                    db.log_execution(tool_name, tool_args, result,
                                      int((time.time() - _tool_t0) * 1000),
                                      conversation_id=conversation_id)
                except Exception:
                    pass
                # v2.215 — Proof-Carrying Actions : chaque appel reçoit une preuve durable
                # (arguments expurgés, résultat, durée, vérification et indication de rollback).
                try:
                    import mission_os as _mission_os
                    _mission_os.record_action(
                        conversation_id=conversation_id,
                        tool_name=tool_name,
                        arguments=tool_args,
                        result=result,
                        duration_ms=int((time.time() - _tool_t0) * 1000),
                    )
                except Exception:
                    pass

                # Suivi pour l'auto-réparation : compte OK/erreur + trace compacte.
                _executed_tool_names.add(tool_name)
                if _is_tooling_failure(result):
                    _run_err += 1
                    _emsg = result.get("error") or result.get("stderr") or "échec"
                    _run_trace.append(f"❌ {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:140]}) → ERREUR: {str(_emsg)[:200]}")
                else:
                    _run_ok += 1
                    _run_trace.append(f"✅ {tool_name} OK")
                    # Golden path : on retient la séquence d'outils RÉUSSIS (args compacts).
                    _aargs = {k: v for k, v in (tool_args or {}).items() if k != "confirmed"}
                    _run_calls.append({"tool": tool_name,
                                       "args": json.dumps(_aargs, ensure_ascii=False)[:90] if _aargs else ""})

                # v2.138 — signal de fiabilité composée (voir commentaire à la déclaration de
                # _long_chain_logged) : une seule trace par tour, pas une par outil.
                if not _long_chain_logged and (_run_ok + _run_err) > 8:
                    _long_chain_logged = True
                    try:
                        import audit as _audit
                        _audit.log_action(
                            "_long_tool_chain", {"count": _run_ok + _run_err, "query": (_user_query or "")[:200]},
                            {"note": "Chaîne d'outils longue — la fiabilité composée se dégrade au-delà de 8 appels."},
                            source="chat",
                        )
                    except Exception:
                        pass

                # Apprentissage : si l'outil a réussi, mémoriser qu'il convient à
                # ce type de demande → routing de plus en plus juste avec l'usage.
                if isinstance(result, dict) and not result.get("error") and _user_query:
                    try:
                        import tool_router
                        await tool_router.record_success(_user_query, tool_name)
                    except Exception:
                        pass

                tool_results_for_db_step.append({
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "result": result,
                })

                # Ajouter le résultat dans la boucle Ollama
                # Truncate very large results to protect context window:
                # Full result is sent to frontend/DB; Ollama only gets a summary.
                result_str = json.dumps(result, ensure_ascii=False)
                MAX_TOOL_RESULT_CHARS = 4000
                if len(result_str) > MAX_TOOL_RESULT_CHARS:
                    # Keep critical fields, truncate large text blobs
                    try:
                        compact = {}
                        if isinstance(result, dict):
                            for k, v in result.items():
                                if k in ("error", "success", "message", "path", "url", "title",
                                         "status", "count", "hash", "result", "translated",
                                         "rows_count", "entries_count", "pages", "total_pages"):
                                    compact[k] = v
                                elif isinstance(v, str) and len(v) > 500:
                                    compact[k] = v[:500] + f"…[{len(v)-500} chars tronqués]"
                                elif isinstance(v, list) and len(v) > 20:
                                    compact[k] = v[:20] + [f"…+{len(v)-20} éléments"]
                                else:
                                    compact[k] = v
                            result_for_ollama = json.dumps(compact, ensure_ascii=False)
                        else:
                            result_for_ollama = result_str[:MAX_TOOL_RESULT_CHARS] + "…[tronqué]"
                    except Exception:
                        result_for_ollama = result_str[:MAX_TOOL_RESULT_CHARS] + "…[tronqué]"
                else:
                    result_for_ollama = result_str

                ollama_msgs.append({
                    "role": "tool",
                    "content": result_for_ollama,
                })

            # Sauvegarder les résultats d'outils
            db.create_message(
                conversation_id, "tool",
                json.dumps(tool_results_for_db_step),
                tool_results=tool_results_for_db_step,
            )

        elif (_skill and _skill.get("tools") and not _nudged and use_tools and tools_payload
              and step < MAX_TOOL_STEPS - 1):
            # ── Compétence active mais le modèle a EXPLIQUÉ au lieu d'AGIR ─────
            # (aucun appel natif, rien à récupérer dans le texte). On le corrige
            # UNE fois avec les noms d'outils EXACTS et on relance l'itération.
            _nudged = True
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
            _script_warnings = _scan_dangerous_script_patterns(full_content)
            if _script_warnings:
                _warning_block = (
                    "\n\n---\n⚠️ **Vérification automatique de sécurité** — points à relire avant d'exécuter ce script :\n"
                    + "\n".join(f"- {w}" for w in _script_warnings)
                )
                yield _sse({"type": "text", "text": _warning_block})
                full_content += _warning_block

            _review_mode = _cortex_plan["resolved"]["review"]
            _force_review = _review_mode in {"verify", "council_if_disagreement"}
            _critique = await _run_critique_pass(
                _user_query, full_content, active_model, force=_force_review
            )
            if _critique:
                _critique_block = "\n\n---\n🧠 **Revue critique (2ᵉ modèle)** :\n" + _critique
                yield _sse({"type": "text", "text": _critique_block})
                full_content += _critique_block

            _escalation = await _cortex_disagreement_escalation(_critique, full_content)
            if _escalation:
                _cid, _cargs, _cresult, _cblock = _escalation
                yield _sse({"type": "tool_start", "toolCallId": _cid, "toolName": "ai_model_council", "args": _cargs})
                yield _sse({"type": "tool_end", "toolCallId": _cid, "result": _cresult})
                _executed_tool_names.add("ai_model_council")
                if _cblock:
                    yield _sse({"type": "text", "text": _cblock})
                    full_content += _cblock

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
                    _cortex_plan["requested"].get("recipe_id"), _run_err == 0, _executed_tool_names
                )
            except Exception:
                pass

            yield _sse({
                "type": "cortex_provenance",
                "provenance": _cortex.provenance(
                    _cortex_plan, active_model, _executed_tool_names,
                    critique=bool(_critique), answer=full_content, conversation_id=conversation_id
                ),
            })
            yield _sse({"type": "done"})
            return

    # Trop d'étapes (MAX_TOOL_STEPS atteint) — v2.126 : jusqu'ici on terminait la boucle
    # SANS RIEN RENVOYER, ni texte ni message sauvegardé — l'utilisateur voyait le flux
    # s'arrêter net après le dernier tool_end, sans aucune réponse. C'est exactement le
    # symptôme rapporté (« Marvin continue de réfléchir sans rien faire ») : reproduit en
    # réel avec une requête de recherche web qui a enchaîné 11 tool_start sans jamais
    # produire de texte. On force maintenant UN dernier appel, SANS outils, pour obtenir
    # une synthèse de ce qui a déjà été trouvé plutôt qu'un silence total.
    ollama_msgs.append({"role": "user", "content": (
        "⛔ Tu as atteint la limite d'appels d'outils pour ce tour. Tu ne peux PLUS utiliser "
        "aucun outil. Réponds MAINTENANT, en français, avec une synthèse aussi complète que "
        "possible de ce que tu as déjà trouvé pour répondre à la demande initiale de "
        "l'utilisateur. Si des informations manquent encore, dis-le clairement plutôt que de "
        "rester silencieux."
    )})
    full_content = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)) as _final_client:
            async with _final_client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model":   active_model,
                        "system":  system_prompt,
                        "messages": ollama_msgs,
                        "stream":  True,
                        "options": _ollama_options,
                        "keep_alive": "30m",
                    },
            ) as resp:
                if resp.status_code == 200:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg_part = chunk.get("message", {})
                        token = msg_part.get("content", "")
                        if token:
                            full_content += token
                            yield _sse({"type": "text", "text": token})
    except Exception:
        pass

    if not full_content.strip():
        full_content = ("Je n'ai pas réussi à conclure cette recherche dans le nombre d'étapes "
                         "autorisées. Peux-tu préciser ta demande ou me demander de continuer ?")
        yield _sse({"type": "text", "text": full_content})

    _script_warnings = _scan_dangerous_script_patterns(full_content)
    if _script_warnings:
        _warning_block = (
            "\n\n---\n⚠️ **Vérification automatique de sécurité** — points à relire avant d'exécuter ce script :\n"
            + "\n".join(f"- {w}" for w in _script_warnings)
        )
        yield _sse({"type": "text", "text": _warning_block})
        full_content += _warning_block

    _review_mode = _cortex_plan["resolved"]["review"]
    _force_review = _review_mode in {"verify", "council_if_disagreement"}
    _critique = await _run_critique_pass(
        _user_query, full_content, active_model, force=_force_review
    )
    if _critique:
        _critique_block = "\n\n---\n🧠 **Revue critique (2ᵉ modèle)** :\n" + _critique
        yield _sse({"type": "text", "text": _critique_block})
        full_content += _critique_block

    _escalation = await _cortex_disagreement_escalation(_critique, full_content)
    if _escalation:
        _cid, _cargs, _cresult, _cblock = _escalation
        yield _sse({"type": "tool_start", "toolCallId": _cid, "toolName": "ai_model_council", "args": _cargs})
        yield _sse({"type": "tool_end", "toolCallId": _cid, "result": _cresult})
        _executed_tool_names.add("ai_model_council")
        if _cblock:
            yield _sse({"type": "text", "text": _cblock})
            full_content += _cblock

    db.create_message(conversation_id, "assistant", full_content)

    # Enregistre tout de même l'issue de la compétence (souvent un signe de faiblesse).
    _up_msg = _finalize_skill_outcome()
    if _up_msg:
        yield _up_msg
    try:
        _cortex.record_recipe_outcome(
            _cortex_plan["requested"].get("recipe_id"), _run_err == 0, _executed_tool_names
        )
    except Exception:
        pass
    yield _sse({
        "type": "cortex_provenance",
        "provenance": _cortex.provenance(
            _cortex_plan, active_model, _executed_tool_names,
            critique=bool(_critique), answer=full_content, conversation_id=conversation_id
        ),
    })
    yield _sse({"type": "done"})
