"""
Marvin Backend — FastAPI application principale.
Lance avec : uvicorn main:app --host 0.0.0.0 --port 8005
(ne pas utiliser --reload : coupe les streams SSE lors des changements de fichiers)
"""
import json
import base64
import re as _re
import asyncio as _asyncio
import sys
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Body, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, Response
from pydantic import BaseModel, Field
from typing import Any

import database as db
import tools as tool_module
from agent import run_agent, _refresh_model_cache
import chat_turn_runtime
from api.backups import router as backups_router
from api.billing import router as billing_router
from api.calendar import router as calendar_router
from api.coding import router as coding_router
from api.conversations import router as conversations_router
from api.content import router as content_router
from api.connections import router as connections_router
from api.cortex import router as cortex_router
from api.cron_monitor import router as cron_monitor_router
from api.ssh import router as ssh_router
from api.storage import router as storage_router
from api.health import router as health_router
from api.diagnostics import router as diagnostics_router
from api.doctor import router as doctor_router
from api.documents import router as documents_router
from api.forge import router as forge_router
from api.evolution import router as evolution_router
from api.history import router as history_router
from api.knowledge import router as knowledge_router
from api.memories import router as memories_router
from api.missions import router as missions_router
from api.model_market import router as model_market_router
from api.multi_agents import router as multi_agents_router
from api.notes import router as notes_router
from api.operations import router as operations_router
from api.projects import router as projects_router
from api.runtime_config import router as runtime_config_router
from api.settings import router as settings_router
from api.skills import router as skills_router
from api.system_tools import router as system_tools_router
from api.tasks import router as tasks_router
from api.technical_docs import router as technical_docs_router
from api.templates import router as templates_router
from api.voice import prewarm_whisper
from api.voice import router as voice_router
from api.avatar import router as avatar_router
from api.vm_lab import router as vm_lab_router
from api.workflows import router as workflows_router
from app_version import APP_VERSION
from config import (
    FRONTEND_URL, BACKEND_PORT, DANGEROUS_TOOLS,
    PERMISSION_SECURE, PERMISSION_STANDARD, PERMISSION_EXPERT, DEFAULT_PERMISSION_LEVEL,
    SECURE_BLOCKED_TOOLS, BACKEND_DIR,
)
from runtime_supervisor import RuntimeSupervisor
from runtime_workers import (
    build_tool_index as _build_tool_index,
    database_backup_worker as _db_backup_worker,
    health_trend_worker as _health_trend_worker,
    memory_consolidation_worker as _memory_consolidation_worker,
    prewarm_default_models as _prewarm_default_model,
    skill_night_learning_worker as _skill_night_learning_worker,
)
from communication_workers import (
    background_scale as _bg_scale,
    calendar_sync_worker as _calendar_sync_worker,
    email_automation_worker as _email_automation_worker,
    email_watch_worker as _email_watch_worker,
    event_reminder_worker as _event_reminder_worker,
)
from proactive_service import (
    get_config as _get_proactive_cfg,
    in_quiet_hours as _in_quiet_hours,
    proactive_worker as _proactive_worker,
    run_anticipation,
    run_evening_recap,
    run_morning_briefing,
    with_defaults as _proactive_with_defaults,
)
from cron_runtime import (
    cron_worker as _cron_worker,
    drain_run_agent as _drain_run_agent,
    long_task_resume_tick as _long_task_resume_tick,
)

# v2.279 — contexte de session extrait d'agent.py : compaction injectable, captures
# multimodales bornées au dossier de conversation et nettoyage des fichiers orphelins.
# v2.278 — revue indépendante des réponses et actions extraite d'agent.py derrière
# une interface injectable, sans modifier les déclencheurs Cortex ni le comportement SSE.
# v2.277 — frontière d'exécution des outils extraite d'agent.py : registre injectable,
# reçus idempotents, erreurs et récupération des appels textuels derrière une façade stable.
# v2.276 — budget Cortex adaptatif : 3/10/16/24 étapes et plafond temporel selon effort,
# arrêt dès satisfaction et consommation publiée dans la provenance de la réponse.
# v2.275 — transport SSE frontend partagé : reconnexion après coupure en milieu de réponse
# avec afterEvent, sans dupliquer texte, outils, raisonnement ou lecture vocale.
# v2.274 — producteur de tour détaché du navigateur et journal SSE SQLite rejouable;
# une reconnexion reprend au curseur sans relancer le LLM ni ses actions.
# v2.273 — requestId propagé du chat et reçus SQLite transactionnels : une action
# terminée est rejouée depuis son reçu; une interruption ambiguë n'est jamais réexécutée.
# v2.272 — matrice et filtrage des outils extraits d'agent.py; plafond désormais
# déterministe entre deux processus Python malgré le hash seed des ensembles.
# v2.271 — constructeur du prompt système extrait d'agent.py; date française sans
# locale globale afin de conserver un comportement déterministe entre workers.
# v2.270 — inventaire Ollama, profils et détection sensible extraits d'agent.py;
# cloud_routing.py reste l'autorité des modes local/cloud et des modèles Cloud.
# v2.269 — adaptateurs UI/Ollama/SSE extraits d'agent.py et durcis contre les parties
# multimodales ou appels d'outils mal formés, sans changer le protocole public.
# v2.268 — sécurité déterministe extraite d'agent.py : validation des arguments JSON
# et scanner de scripts/documents dangereux, injectés derrière les alias historiques.
# v2.267 — trois fuites de connexions SQLite OAuth/Google corrigées; invariant AST
# interdisant désormais toute ouverture directe non bornée hors de db_connection.py.
# v2.266 — premières politiques pures extraites d'agent.py : intention commande/texte,
# titrage provisoire et détection exacte d'outils, avec alias de boucle inchangés.
# v2.265 — connexion SQLite centralisée et premier repository conversations/messages;
# la façade database.py, les transactions et tous les contrats publics restent compatibles.
# v2.264 — migrations SQLite versionnées, checksumées et transactionnelles; schéma cœur
# Python autonome et initialiseur Next.js neuf corrigé sans modifier les données existantes.
# v2.263 — domaine Base de connaissances IT extrait sous tool_domains/it_knowledge.py;
# recherche, classement déterministe, usage et ajout restent derrière la façade tools.py.
# v2.262 — premier domaine de tools.py extrait : quiz et répétition espacée sous
# tool_domains/quiz.py avec injection du générateur et registre public inchangé.
# v2.261 — moteur cron et reprise agentique longue extraits dans cron_runtime.py;
# exécution, délai, persistance, détection de stagnation et notifications conservés.
# v2.260 — service proactif extrait, dépendance des voix rétablie et lecture ffmpeg bornée;
# les endpoints historiques utilisent les mêmes alias et contrats de réponse.
# v2.259 — workers e-mail, automatisation, rappels et synchronisation agenda extraits dans
# communication_workers.py avec façade historique et cadence préservées.
# v2.258 — six workers transverses extraits dans runtime_workers.py derrière leurs alias
# historiques : préchauffage, index outils, apprentissage, sauvegarde, mémoire et santé.
# v2.257 — cycle de vie consolidé : superviseur idempotent et observable des workers,
# collecte des erreurs et arrêt garanti par le bloc finally du lifespan FastAPI.
# v2.256 — démarrage avatar fiabilisé et audit global consigné sans extraction de modules.
# v2.250 — Suivi persistant des Coding Missions dans le chat, progression et corrections
# visibles après navigation; reprise du dernier snapshot et diagnostics natifs ciblés renforcés.
# Avatar Electron conversation/compact, activation locale, suivi Code et voix sérialisée par
# génération pour empêcher tout chevauchement. Contrôles UFW réels renforcés dans Code Forge.
# v2.249 — Continuité Chat/Code Workspace : reprise déterministe de la dernière mission,
# lecture des livrables refusés depuis leur snapshot durable, statut terminal piloté par le
# job Auto et diagnostics Bats visibles. Aucun outil ni aucune capacité existante supprimés.
# v2.248 — Engineering Runtime : contrat universel additif des outils, événements Coding Mission
#   persistants diffusés en SSE vers Chat/Workspace, réparations ciblées, Definition of Done
#   déterministe et Delivery Pack. L'acceptation Forge reste provisoire jusqu'aux validations
#   natives finales et trois causes différentes ne bloquent plus une mission until_success.
# v2.247 — continuité du flux chat pendant la navigation, snapshots Code Workspace lisibles,
# capacités Docker/VM factuelles et transfert Debian natif verrouillé et validé en réel.
# v2.246 — restauration fiable des historiques après navigation; cache de routes Turbopack
# auto-réparé au démarrage et build simultané bloqué avant toute corruption.
# v2.245 — vues globales Lecture, Technique et Audit; export local JSON/Markdown expurgé.
# v2.244 — conversation human-first : activités regroupées, résultats techniques repliés et
# réponses longues lisibles sans suppression du détail ni des preuves.
# v2.243 — Ultra débridé strictement cloud sans repli local; Test Forge escalade les scripts
# systemd vers une VM Debian restaurée et conserve un snapshot temporaire inspectable.
# v2.242 — Code Workspace prompt-first depuis l'UI et le chat, Test Forge Debian prouvé,
# blocage déterministe des faux succès Forge et onglets d'accès rapide réellement interactifs.
# v2.241 — installations Debian/Windows sans assistance pilotées par Marvin, jobs persistants,
# toolchains Windows, UI Automation Hyper-V et smoke natif checkpointé.
# v2.240 — VM Lab : vérification cryptographique des ISO, profils Hyper-V Generation 2,
# planification de capacité et provisionneur explicite sans altérer les anciennes VM.
# v2.239 — bibliothèque Marvin classifiée : ISO/VM/workspaces locaux, exports utilisateur,
# inventaire, racines portables et refus des disques réseau ou synchronisés pour les VHDX.

# v2.238 — chemins portables : Known Folders Windows, redirections OneDrive/entreprise,
# alias de saisie et configuration MCP générée depuis l'installation courante.
# v2.237 — runner Windows natif Hyper-V : checkpoints, PowerShell Direct, secret DPAPI,
# compte invité non administrateur et réseau coupé pendant l'exécution des tests.
# v2.236 — superviseur Auto persistant : file durable, reprise au démarrage, annulation,
# budgets, contexte borné du dépôt et application transactionnelle dans le worktree isolé.
# v2.235 — Repository Intelligence et mode Auto borné : contrat de dépôt, règles AGENTS/CLAUDE
# hiérarchiques, worktree Git isolé, budgets et routage strict des validations Windows natives.
# v2.234 — Code Workspace : supervision des Coding Missions, snapshots, preuves, matrice
# de toolchains et documentation officielle, avec préparation/reprise contrôlée via le chat.
# v2.233 — Engineering Knowledge Radar : documentation officielle ciblée par langage,
# fraîcheur/ETag/hash, source firewall et injection contrôlée dans Code Forge.
# v2.232 — Go Forge 1.26.5 et Advanced Coding Mission : exécution Linux, cross-build Windows,
# matrice honnête des toolchains, snapshots durables et reprise optimiste des projets longs.
# v2.231 — Production Contract Gate : preuves déterministes d'analyse/tests, API Python
# typée, installation jetable des dépendances et SBOM CycloneDX avant acceptation finale.
# v2.230 — Deliverable Bundle : Code Forge conserve les projets multi-fichiers, refuse les
# chemins dangereux et les dépendances non verrouillées, puis transmet tout le workspace
# aux analyseurs et runners Windows/Linux avant toute certification production.
# v2.229 — Windows Test Forge validé réellement : suivi du client 24H2, installation
# PowerShellGet non interactive, filtrage LAN par processus et smoke test Pester live.
# v2.228 — Test Forge Windows Sandbox et intégrations Linux connectées : dépendances
#   réellement installées, tests relancés par le runner, réseaux privés bloqués sous Windows.
# v2.227 — Model Market spécialisé par rôle, sélection adaptative par phase et parc
#   Ollama Cloud recommandé auto-synchronisé ; tous les tags cloud valides restent ajoutables.
# v2.226 — Test Forge : tests générés, exécution Docker hors ligne et intégration
# Internet dans Debian 13 jetable avant toute livraison de code de production.
# v2.225 — Code Forge : architecture, implémentation, double revue, réparation,
#   gatekeeper final et validation syntaxique sans exécuter le code généré.
# v2.224 — vérification sémantique contradictoire et Adaptive Team Runtime :
#   composition bornée de Research Swarm, Cortex Search et Council.
# v2.223 — Evidence Fabric 2 et Arena aveugle : fraîcheur, corroboration, duels
#   anonymisés, notes structurées et influence humaine après trois comparaisons.
# v2.222 — Frontier Arena et Evidence Fabric : comparaison neutre, provenance par
#   affirmation, dette épistémique et Source Firewall déterministe.
# v2.221 — parcours UI complets : SSE Swarm, cycle Evolution et checkpoints Canvas.
# v2.220 — Evolution Lab, Mission Canvas et Research Swarm durable.
# v2.217 — Model Market et Research Swarm : scorecards passives et recherche parallèle sourcée.
# v2.216 — Memory Mesh et Truth Ledger : mémoires typées et affirmations reliées aux preuves.
# v2.215 — Mission OS et Proof-Carrying Actions : état durable, checkpoints et preuves expurgées.
# v2.214 — Cortex Search : stratégies concurrentes, cinq vérificateurs spécialisés et arbitrage.
# v2.213 — Marvin Forge : corpus agentique, graders déterministes, pass^k, API et tableau de bord.
# Le démarrage détecte aussi les ports exclus par Docker/Hyper-V et déplace Ollama localement.
# v2.212 — un lancement sans console UTF-8 (Start-Process/WMI/Planificateur Windows)
# ne doit jamais faire échouer FastAPI parce qu'un message de diagnostic contient un emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, OSError):
        pass

# ══════════════════════════════════════════════════════════════════════════════
# Moteur CRON — exécution planifiée des outils
# ══════════════════════════════════════════════════════════════════════════════

from contextlib import asynccontextmanager

# ── Marvin proactif : briefing matinal automatique ──────────────────────────────
@asynccontextmanager
async def lifespan(app_instance):
    """Initialisation au démarrage : cache des modèles + worker cron + surveillance email + pré-chargement."""
    chat_turn_runtime.recover_orphaned_turns()
    chat_turn_runtime.prune()
    # Auto-configuration : choisit les meilleurs modèles selon le matériel (AVANT le pré-chargement)
    try:
        import auto_config
        ac = await auto_config.apply_auto_config()
        if ac.get("enabled"):
            print(f"[Marvin] 🧩 Auto-config : {ac['hardware']['gpu']} ({ac['hardware']['vram_gb']} Go) → {ac['applied']}")
    except Exception as e:
        print(f"[Marvin] ⚠️ Auto-config échouée : {e}")
    await _refresh_model_cache()
    import coding_jobs as _coding_jobs
    import engineering_radar as _engineering_radar
    import model_market as _model_market

    supervisor = RuntimeSupervisor()
    app_instance.state.runtime_supervisor = supervisor
    coding_jobs_started = False
    try:
        supervisor.start("cron", _cron_worker)
        supervisor.start("ollama-prewarm", _prewarm_default_model)
        supervisor.start("whisper-prewarm", prewarm_whisper)
        supervisor.start("email-watch", _email_watch_worker)
        supervisor.start("email-automation", _email_automation_worker)
        supervisor.start("event-reminders", _event_reminder_worker)
        supervisor.start("calendar-sync", _calendar_sync_worker)
        supervisor.start("proactive-briefing", _proactive_worker)
        supervisor.start("skill-night-learning", _skill_night_learning_worker)
        supervisor.start("tool-index", _build_tool_index)
        supervisor.start("database-backup", _db_backup_worker)
        supervisor.start("memory-consolidation", _memory_consolidation_worker)
        supervisor.start("health-trend", _health_trend_worker)
        supervisor.start("cloud-model-fleet", _model_market.sync_recommended_cloud_models)
        supervisor.start("engineering-radar", _engineering_radar.background_worker)
        _coding_jobs.start_pending()
        coding_jobs_started = True
        try:
            import skills
            skills.seed_examples()
        except Exception:
            pass
        yield
    finally:
        await chat_turn_runtime.shutdown()
        try:
            import web_browser
            await web_browser.close()
        except Exception:
            pass
        if coding_jobs_started:
            await _coding_jobs.shutdown()
        await supervisor.shutdown()

# v2.79.0 — Compétences fiabilisées : (1) nomic-embed-text requis pour le matching
#   sémantique (sinon dégradé en lexical) ; (2) les compétences EXÉCUTENT vraiment les
#   outils — filet `_salvage_text_tool_calls` (récupère les appels écrits en texte/JSON,
#   résout les noms hallucinés) + re-prompt correctif quand le modèle explique au lieu
#   d'agir + prompt durci (agent.py) ; (3) invention de compétence robuste via parser
#   JSON tolérant `_parse_skill_json` (résiste aux quotes/sauts de ligne dans `body`).
# v2.80.0 — Compétences PLUS FORTES + AUTO-RÉPARANTES : (1) `pc_run_command` auto-route
#   vers PowerShell quand il détecte un cmdlet (fin de l'erreur « Get-… non reconnu » en
#   cmd) ; (2) moteur d'auto-upgrade — stats par compétence (skills_stats.json), versioning
#   automatique (data/skills/_versions/), `skills.upgrade_skill` (le LLM ré-écrit une
#   compétence après un échec d'outil) déclenché en arrière-plan par agent.py, + endpoints
#   stats/upgrade/versions/rollback ; (3) filet `_salvage_text_tool_calls` étendu au motif
#   nom-avant-accolade (profil chat 3b) ; (4) win_event_log : message clair si droits admin requis.
# v2.81.0 — 🥇 GOLDEN PATH (les compétences apprennent du SUCCÈS) : quand une compétence
#   réussit proprement, la SÉQUENCE d'outils gagnante est mémorisée (skills.record_success_trace,
#   garde la plus courte = la + efficace) et RÉINJECTÉE comme exemple few-shot au prochain
#   déclenchement (agent.py) → exécution + fiable sur petit modèle. Affiché dans l'UI Skills
#   (🥇 Déroulé appris). Raffinements : `_is_tooling_failure` ignore les erreurs ENVIRONNEMENTALES
#   (timeout, droits admin) → pas de faux auto-upgrade ; l'upgrade PRÉSERVE triggers+description
#   (le matching reste stable, seule la MÉTHODE est corrigée) ; win_service_action accepte `query`.
# v2.82.0 — 📦 RESSOURCES DE COMPÉTENCE (progressive disclosure) : une compétence peut
#   embarquer des fichiers de référence (modèles, tables de prix, check-lists) dans un sidecar
#   data/skills/<nom>.resources/. À l'activation, `skills.resources_prompt_block` injecte le
#   contenu des petites ressources INLINE et liste les gros fichiers/binaires à lire via
#   `file_read`. Endpoints CRUD /api/skills/{name}/resources (+ /upload binaire) + UI (panneau
#   « 📦 Ressources » dans la page Skills). Les ressources survivent à un rollback (sidecar).
#   `_is_tooling_failure` ignore aussi les « argument manquant » (entrée utilisateur ≠ défaut skill).
# v2.83.0 — 🔎 MINING PROACTIF + override modèle par machine : (1) `skills.suggest_skills`
#   analyse les demandes récurrentes (db.get_recent_user_messages) et propose des compétences
#   NON couvertes (parser bulletproof = collecteur récursif d'objets JSON ; exclusion stricte
#   à 0.80 pour ne pas écarter à tort) ; endpoints /api/skills/suggest(+/dismiss) + section UI
#   « 🔎 Suggestions ». (2) Réglage `model_overrides` (data/, distribuable) épingle un modèle par
#   profil — ici chat+agent+analysis = qwen2.5:14b (RTX 3080) → un seul modèle résident, zéro thrash.
# v2.84.0 — 📦 EMPORIUM (Winget, V3 phase 1) : gestionnaire de paquets universel. 5 outils
#   (winget_search/list_upgrades/install/upgrade/uninstall) + endpoints REST /api/winget/* +
#   onglet « Emporium ». Parser winget ROBUSTE par POSITIONS DE COLONNES (split('\r')[-1] pour
#   retirer le spinner, bornes = débuts de mots de l'en-tête) — fiable même quand un nom long
#   ne laisse qu'1 espace avant l'ID (cas VLC). Install/upgrade/uninstall = silencieux + confirmés.
#   Pilotable depuis le chat ET l'onglet. 261 → 266 outils.
# v2.85.0 — 🏛️ PANTHEON (V3 phase 2) + THÈME VIVANT. Pantheon : 8 outils d'optimisation
#   (system_restore_point, registry_get/backup/set, tweak_telemetry, tweak_debloat_list/remove,
#   tweak_network_harden) — toute écriture fait d'ABORD une sauvegarde (.reg / point de
#   restauration) + confirmation (réversible) ; endpoints /api/pantheon/* + onglet. 266 → 274
#   outils. Thème « Oracle » VIVANT (globals.css) : fond animé (aurore holographique + cœur
#   numérique qui bat), avatar SVG animé (LivingAvatar, s'accélère quand Marvin réfléchit),
#   titres holographiques, cartes vivantes. Re-skin global via variables CSS (--bg-primary translucide).
# v2.86.0 — 🧹 CATHARSIS + 🎛️ CODEX (V3 phases 3 & 4) → VISION V3 COMPLÈTE (4 piliers).
#   Catharsis (2 outils) : catharsis_scan (analyse l'espace récupérable par catégorie, SANS
#   supprimer — fix clé : chemins en DOUBLE quotes PS pour développer $env:TEMP) + catharsis_clean
#   (purge confirmée). Codex (5 outils) : os_power_plan, os_dark_mode, os_firewall,
#   os_network_adapters, os_hibernation (lecture libre, écriture confirmée). Endpoints
#   /api/catharsis/* et /api/codex/* + onglets. 274 → 281 outils. + execute_pc_run_powershell
#   force la sortie console en UTF-8 (fin des accents mojibake dans TOUS les outils PS).
# v2.87.0 — RETRAVAIL ERGONOMIE (retours utilisateur) : (1) onglets renommés en FONCTIONNEL
#   (Logiciels/Optimisation/Nettoyage/Système — plus de noms antiques en façade) ; (2) Logiciels :
#   winget_list_installed (chat-usable) + liste des 259 apps installées avec Désinstaller par ligne ;
#   (3) Nettoyage : refonte en TUILES façon CCleaner (13 catégories groupées Windows/Navigateurs/
#   Système + corbeille) ; (4) AVATAR VIVANT visible : grand Oracle animé (148px) sur l'accueil du
#   chat + header + sidebar (cœur qui bat, s'accélère quand Marvin réfléchit) ; (5) barre de chat
#   restylée (bordure holographique animée, glow or/cyan au focus). 282 outils.
# v2.88.0 — Panneau CONVERSATIONS retravaillé (app/page.js) : recherche/filtre en direct,
#   groupement par DATE (Aujourd'hui / 7 / 30 jours / Plus ancien via updated_at), RENOMMAGE
#   inline (✏️ → PUT /api/conversations/{id} {title}), actions révélées au survol, style vivant.
#   + sidebar groupée en sections (Assistant/PC & Système/Organisation/IA/Automatisation/Réglages).
# v2.89.0 — 🛡️ GARDE DE SÉCURITÉ D'EXÉCUTION (security.py, défense en profondeur). Screen
#   toute commande shell/PowerShell/SSH AVANT exécution ; BLOQUE EN DUR le catastrophique
#   irréversible (format X:, diskpart clean, Remove-Item -Recurse racine/système, rm -rf /,
#   mkfs, dd of=/dev/sd, cipher /w, bcdedit /delete, fork bomb…) — même en Expert / confirmé.
#   Conservateur (zéro faux positif testé : temp cleanup, suppression d'1 fichier, rm ./node_modules
#   passent). Câblé dans pc_run_command / pc_run_powershell / ssh_exec. C'est la brique
#   réutilisable du pattern « allowlist / séparation de privilèges » (cf. proposition sidecar).
# v2.90.0 — 🔐 SIDECAR ÉLEVÉ (séparation de privilèges, pattern proposé par l'utilisateur).
#   Nouveau démon séparé `elevated_daemon.py` : SEUL ce petit process tourne en administrateur
#   (le backend principal peut rester utilisateur normal). Canal IPC local = Named Pipe Windows
#   avec jeton partagé (`elevated_protocol.py` — contourne le piège MIC : un pipe créé par un
#   process élevé refuse par défaut l'écriture depuis un process non élevé ; on force l'étiquette
#   d'intégrité à Medium via SDDL). N'accepte qu'une ALLOWLIST (run_command/run_powershell/ping)
#   et revérifie `security.screen_command()` CÔTÉ ÉLEVÉ AUSSI (défense en profondeur — c'est en
#   admin que ça compte le plus). Nouvel outil `pc_run_elevated` (confirmation obligatoire,
#   bloqué en niveau Sécurisé). `elevated_client.py` = client utilisé par le backend, échoue
#   proprement si le démon n'est pas lancé. Lancement : `launch_elevated_daemon.ps1` (1 invite
#   UAC standard). **Prouvé en ÉLÉVATION RÉELLE** (pas seulement en théorie) : `net session`
#   (Erreur 5 refusé en non-admin) → succès via le canal élevé ; `format C:`/`Remove-Item
#   C:\ -Recurse` → bloqués même via le démon élevé ; jeton invalide → refusé. Journal d'audit
#   (source="elevated") vérifié. Le backend principal continue de tourner tel quel pour l'instant
#   (bascule complète en non-admin = étape suivante, opt-in, à faire avec l'utilisateur).
# v2.91.0 — 🌐 RÉSEAU PRO + 🧾 INVENTAIRE MATÉRIEL, portés d'un fork parallèle du projet
#   (secretary-ai-codex-groky-alpha, audité puis transplanté manuellement — pas de fusion en
#   bloc). 6 outils réseau : net_nmap_scan (nmap.exe si présent, sinon repli TCP asynchrone
#   interne), net_service_detect (bannières TCP), net_http_probe (statut/titre/en-têtes de
#   sécurité), net_tls_check (certificat : émetteur/SAN/expiration), net_subnet_sweep (CIDR
#   borné), net_route_diagnostics (connectivité complète). Scans larges → confirmation
#   obligatoire (_net_targets). + pc_hardware_specs : inventaire matériel (fabricant/modèle/
#   série, CPU, RAM, disques, GPU, cartes réseau) avec liens officiels support/pilotes déduits
#   du fabricant détecté (Dell/HP/Lenovo/ASUS/Acer/Surface/MSI/GIGABYTE/ASRock/Intel/AMD/
#   NVIDIA/Samsung/WD/Seagate/Crucial). Les 7 outils sont TESTÉS EN RÉEL sur cette machine (pas
#   seulement importés) : TLS google.com réel, ports RDP/SMB détectés localement, inventaire
#   matériel exact (ASUS STRIX Z270F, i7-7700K, RTX 2060, 32 Go RAM). 283 → 290 outils.
# v2.92.0 — 🎮 DÉTECTION GPU TEMPS RÉEL + amorce AMD natif. `local_video.get_device_info()`
#   passe d'un cache figé (permanent jusqu'au redémarrage) à un TTL COURT (20s) — corrige le
#   vrai bug trouvé en session (mémoire disait RTX 3080, la machine a une RTX 2060 : le cache
#   ne s'était JAMAIS rafraîchi). Nouvel outil chat `pc_gpu_status` (+ `refresh=true` pour forcer
#   une redétection immédiate juste après un changement de carte — utile pour tester des cartes
#   clients). Amorce DirectML (`_detect_directml_gpu`) : seule voie native pour faire tourner
#   PyTorch sur un GPU AMD sous Windows (ROCm = Linux uniquement) ; se dégrade proprement si le
#   paquet est absent. **Constat honnête** : `torch-directml` n'a AUCUNE version compatible avec
#   Python 3.14 (ce venv) → le calcul AMD natif reste bloqué par l'environnement, pas par le code
#   (options : venv dédié Python 3.10/3.11 pour la vidéo, à discuter, PAS fait silencieusement).
#   290 → 291 outils.
# v2.93.0 — 🪟 CATALOGUE « Windows+ » (win_quick_launch/win_quick_launch_list), 29 raccourcis
#   groupés (God Mode / Paramètres Windows / Panneaux legacy / Outils admin / Performance /
#   Maintenance / Dossiers utiles), porté du fork — CATALOGUE DE NAVIGATION SEULEMENT (leur
#   système de tweaks/registre séparé n'est PAS repris, il chevauche Pantheon existant). Risque
#   quasi nul : `os.startfile` (+ repli `cmd /c start`), n'écrit rien sauf God Mode (dossier vide
#   standard). Testé en réel : ouverture du dossier Temp confirmée. + routage par mots-clés pour
#   les 3 derniers ajouts (pc_gpu_status, win_quick_launch*) — leçon apprise cette session :
#   un outil non découvert par le filtre de mots-clés n'est jamais proposé au LLM. 291 → 293 outils.
# v2.94.0 — 🎙️ VOIX CONSOLIDÉE + choix du micro. Nouveau module partagé
#   `lib/voice/voiceRecorder.js` : ChatInput.jsx et useVoice.js avaient CHACUN leur propre copie
#   de la capture micro (getUserMedia + VAD + MediaRecorder), avec les MÊMES 3 défauts dupliqués
#   deux fois — aucun choix de périphérique (toujours le micro système par défaut, impossible de
#   passer sur un casque Bluetooth), mimeType 'audio/webm' figé sans repli, VAD peu sensible
#   (seuil 0.025/1100ms ratait les phrases courtes). Centralisé en un seul module : repli robuste
#   à 3 niveaux (deviceId exact → ideal → défaut, efface le choix mémorisé s'il est cassé —
#   micro Bluetooth éteint/débranché ne bloque plus rien), détection MIME réelle du navigateur,
#   VAD réglé à 0.006/120ms/900ms. Sélecteur de micro (▾) ajouté dans ChatInput ET dans la page
#   /vocal, backés par `useVoice()` (device list + persistance localStorage, partagés via
#   ChatContext). Erreurs micro/transcription remontées à l'UI (fini l'échec silencieux).
#   TESTÉ EN RÉEL (Playwright, permission micro accordée) : périphériques système réels détectés
#   dont un vrai casque Bluetooth (Bose QC35 II), sélection → persistance localStorage →
#   ré-affichage coché après réouverture du menu, /vocal sans erreur console. 293 outils (inchangé
#   — travail frontend, pas de nouvel outil).
# v2.95.0 — 📖🌙 LEARNING LOG + CONSOLIDATION NOCTURNE, transplanté du fork Codex/Grok. Jusqu'ici
#   Marvin apprenait déjà des échecs/réussites PAR compétence (auto-upgrade sur échec d'outil,
#   golden path sur succès — v2.79-81) mais rien ne consolidait cet apprentissage AU NIVEAU
#   GLOBAL, et rien ne tournait la nuit. Nouveau : `skills.log_learning_event/get_learning_log`
#   — journal persistant (`data/skills_learning_log.json`, 200 derniers événements, avec diffs)
#   de toute création/upgrade/consolidation/oubli de compétence, câblé aux 3 points de création
#   (manuelle, génération ✨, extraction 🧠) + à `upgrade_skill`. `review_and_consolidate_learnings`
#   (le LLM relit son propre log par compétence et peut proposer UNE fusion/consolidation si un
#   vrai pattern se dégage) + `consolidate_obsolete_skills` (archive — jamais supprime — les
#   compétences >30j sans usage et <3 usages au total, rollback possible). Nouveau worker de fond
#   `_skill_night_learning_worker` : cadence 15 min la nuit (22h-6h) vs 25 min le jour — Marvin
#   revoit son apprentissage sans intervention, plus activement la nuit. Endpoints
#   `/api/skills/learning_log` (GET) + `/api/skills/consolidate` (POST, déclenchement manuel) +
#   nouvel outil chat `skill_learning_log` (introspection : « qu'as-tu appris récemment ? »).
#   TESTÉ EN RÉEL : création d'une compétence → événement "create" loggé et relu via l'endpoint
#   et l'outil chat ; consolidation manuelle déclenchée sans erreur (reviewed=null car <3
#   événements, comportement attendu, conservateur) ; worker de fond démarré et tourne sans
#   exception. 293 → 294 outils.
# v2.96.0 — 🩹 CORRECTIF EVENT-LOOP BLOQUANTE + 🎯 OUTIL EXPLICITE RESPECTÉ (audit fork
#   Codex/Grok). Trouvé en auditant `tools.py` : `subprocess.run()` était appelé de façon
#   SYNCHRONE dans des `async def execute_*`, ce qui GÈLE TOUT FastAPI (chat, `/api/health`,
#   tout) pendant la durée de la commande — jusqu'à **30 MINUTES** pour `winget upgrade --all`
#   (timeout=1800s). 12 sites `subprocess.run` directs + 6 appels à `_winget_run` corrigés :
#   tous passent maintenant par `await asyncio.to_thread(...)` (pc_run_command, pc_run_powershell,
#   winget_*, _reg_backup avant chaque tweak Pantheon, clipboard get/set, pc_notify, pc_window_list,
#   net_scan_local, git_info). PREUVE RÉELLE : `ping -n 8` (7,3s) lancé en tâche de fond via
#   `pc_run_command`, `/api/health` interrogé PENDANT l'exécution → répond en 24ms puis 1,6ms
#   (avant ce correctif, `/api/health` aurait attendu les 7,3s). net_ping accepte maintenant
#   `target`/`ip` en alias de `host` (robustesse). + `agent.py` détecte les noms d'outils cités
#   EXPLICITEMENT par l'utilisateur (`_exact_tool_mentions_from_text`) : l'outil nommé est imposé
#   pour le tour (tools_payload restreint) et toute substitution est bloquée à l'exécution
#   (corrige un cas réel du fork : demande `file_find`, le modèle appelait `net_ping`). Testé :
#   détection correcte sur 4 phrases (exact-match + zéro faux positif sur du texte normal).
#   294 outils (inchangé — corrections internes, pas de nouvel outil).
# v2.97.0 — 🎨 REFONTE UI COMPLÈTE — console IA professionnelle. Sur demande explicite de
#   l'utilisateur : « je veux que l'UI ressemble à celle d'une IA pro, repense toute l'UI ».
#   Pivot du thème « Oracle » (or/mystique, aurore animée, cœur qui bat, hexagones antiques —
#   v2.85-2.87) vers une palette graphite neutre + bleu électrique/cyan (`app/globals.css`) :
#   fond fixe opaque (plus d'aurore radiale animée en fond de page), accents #4f8cff/#38bdf8,
#   rayons de bordure resserrés (look outil, pas pilule partout), police mono ajoutée pour les
#   accents techniques. `.holo-text`/`.living-card`/`.breathe`/`.float-y` CONSERVÉES (utilisées
#   dans 7+ fichiers) mais redéfinies en version calme (texte plein, pas de dégradé arc-en-ciel ;
#   survol = relief discret, pas de halo coloré). Migration mécanique de TOUTES les couleurs or
#   codées en dur (#c9a84c/#e8c96d/#e8c96a/#dab95e/#35e0d0 + leurs rgba, 32 fichiers) vers la
#   nouvelle palette — zéro résidu vérifié par grep. `LivingAvatar.jsx` réécrit : l'ancien
#   « Oracle antique » (yeux dorés, hexagone pierre, laurier, circuits gravés) remplacé par un
#   badge de statut géométrique sobre (anneau + cœur qui pulse, un seul accent bleu). Sidebar :
#   suppression de l'icône robot inutilisée (dead code), nettoyage des mentions « Oracle »
#   (tooltip/commentaires). Vérifié en réel (Playwright, 3 pages : accueil chat, Outils,
#   Paramètres) : zéro erreur console, rendu cohérent sur tout l'écran.
# v2.98.0 — 🗂️ REFONTE NAVIGATION — regroupement par sujet + mode vocal fusionné au chat.
#   Sur demande explicite : « travaille la mise en page, regroupe ce qui est du même sujet de
#   façon pro, intuitif ». Constat : ~30 destinations plates dans la sidebar, dont 8 pour "PC &
#   Système" (Outils/Logiciels/Optimisation/Nettoyage/Système/Santé/SSH/Monitoring) et 3 pour
#   les fichiers (Fichiers/Mes documents/Indexation) qui se recoupaient sans que l'utilisateur
#   puisse deviner laquelle contient quoi. **Fusion en 2 hubs à onglets internes** (zéro
#   fonctionnalité perdue) :
#   - `/systeme` (🖥️ PC & Système) : onglets Santé/Logiciels/Optimisation/Nettoyage/Système —
#     regroupe emporium/pantheon/catharsis/codex/sante (SSH et Monitoring restent séparés,
#     sujet différent : machines distantes / supervision continue).
#   - `/fichiers` : onglets Parcourir/Documents/Recherche PC — regroupe files/documents/indexation.
#   Implémentation : chaque ancienne page exporte maintenant sa vue (`XxxView`) réutilisable EN
#   PLUS de son ancien rendu ; l'ancienne route (`/emporium`, `/pantheon`, `/catharsis`, `/codex`,
#   `/sante`, `/files`, `/documents`, `/indexation`) redirige (`router.replace`, useEffect) vers
#   le hub avec le bon onglet préselectionné → tout ancien lien/favori continue de marcher.
#   **Mode vocal fusionné au chat** : `/vocal` avait une UI dédiée (orbe, mode mains libres) qui
#   faisait EXACTEMENT doublon avec le bandeau « Mode vocal actif » déjà présent dans
#   `ChatContainer.jsx` (voix/vitesse/barge-in/toggle, vérifié dans le code avant suppression) —
#   `/vocal` redirige maintenant simplement vers `/`. **Sidebar des conversations repliable**
#   (`app/page.js`) : poignée fine `◀/▶` entre la liste et la zone de chat, état persistant
#   (`localStorage`), CSS désactive la poignée sur mobile (le tiroir mobile existant suffit).
#   Sidebar nav : 30 → ~24 entrées. Vérifié en réel (Playwright) : les 3 anciennes routes
#   redirigent vers les bons onglets, le hub Santé affiche un vrai score 100/100 (294 outils
#   cohérents), le hub Fichiers affiche le vrai contenu du disque, le repli/dépli de la sidebar
#   fonctionne (la zone de chat s'élargit), zéro erreur console sur l'ensemble du parcours.
# v2.99.0 — ⏳ RETOUR VISUEL "MARVIN TRAVAILLE" — sur demande explicite (« je dois savoir que
#   Marvin travaille »). Nouveau `TopLoadingBar` : fine barre de progression animée en haut de
#   l'écran, visible sur N'IMPORTE QUELLE page tant qu'une requête chat est en cours (branchée
#   sur `useChatStatus().isLoading`, donc visible même si l'utilisateur a navigué ailleurs
#   pendant que Marvin répond). Nouveau composant réutilisable `Spinner`/`LoadingRow`
#   (`components/ui/Spinner.jsx`, sablier CSS pur `.spinner-ring`) qui remplace 13 textes
#   "Chargement..." bruts sans aucun signal visuel, répartis sur 12 fichiers (calendar, cron,
#   devis, docs, emails ×2, memoire, monitoring, notes, outils ×2, tasks, video,
#   FileExplorerCard) — désormais tous avec un sablier animé. Le bouton d'envoi du chat
#   (déjà correct) bascule en bouton ⏹ Stop pendant la génération. Aucune fonctionnalité
#   retirée, uniquement des indicateurs de chargement ajoutés/harmonisés. Vérifié en réel
#   (Playwright, 14 pages) : zéro erreur console.
# v2.100.0 — 📊 REFONTE MONITORING (bug de scroll + panneaux fonctionnels). Signalé par
#   l'utilisateur : `/monitoring` n'avait aucun scroll (conteneur racine `minHeight:'100vh'`
#   sans `overflowY`) → les stats/historique en bas de page étaient invisibles. Au-delà du
#   correctif, refonte du concept : la page entière poussait tout à la verticale (une seule
#   longue page à faire défiler). Nouveau pattern **panneaux à défilement indépendant**
#   (`Panel`, maxHeight 560px + overflow interne) : les jauges CPU/RAM/Réseau/Disques restent
#   groupées et visibles sans scroll long, pendant que « Dernières exécutions » et
#   « Statistiques » défilent chacun dans leur propre zone. Historique d'outils enfin
#   exploitable : recherche par nom d'outil + filtre Tout/Succès/Échec (composables), et
#   chaque ligne se déplie au clic pour montrer arguments + résultat/erreur (`PrettyResult`,
#   données déjà en base via `db.list_executions`, jamais affichées avant). Taux d'échec (%)
#   ajouté aux statistiques, coloré selon la sévérité. Vérifié en réel (Playwright) : scroll
#   fonctionne, filtre+recherche combinés isolent correctement (32 échecs `calendar_list`
#   trouvés), dépliage affiche arguments/résultat lisible, zéro erreur console.
# v2.101.0 — 🎯 4 PROPOSITIONS D'ERGONOMIE (validées par l'utilisateur : « je suis ok pour tes
#   4 propositions go »).
#   1) **Toasts unifiés** : `components/ui/Toast.jsx` (ToastProvider/useToast) existait déjà
#      mais n'était monté nulle part — 9 pages (emporium/pantheon/catharsis/codex/sante/skills/
#      documents/indexation) + 3 de plus trouvées en auditant plus large (devis/docs/cron)
#      réinventaient chacune leur propre bandeau `useState`+`setTimeout`. Toutes migrées vers
#      `useToast()` (déstructurer `.toast` — piège découvert et corrigé : le hook renvoie
#      `{addToast, removeToast, toast}`, pas directement les méthodes). Bug annexe corrigé dans
#      `Toast.jsx` : `useAutoClose` utilisait `useState(() => {...})` comme s'il s'agissait de
#      `useEffect` → le timer de fermeture auto n'était jamais nettoyé au démontage (fuite).
#      `ToastProvider` monté une fois dans `layout.js`. `components/chat/FileExplorerCard.jsx`
#      gardé intentionnellement à part (toast positionné à côté du fichier concerné dans l'arbre,
#      pas un bandeau générique — pertinent tel quel).
#   2) **Palette de commandes (Ctrl+K)** : `components/ui/CommandPalette.jsx`, monté globalement,
#      indexe `NAV_SECTIONS` (exporté depuis `Sidebar.jsx`) + une action "Nouvelle conversation".
#      Navigation clavier complète (flèches, Entrée, Échap), ouverture aussi via un bouton dans
#      la sidebar (`window.dispatchEvent(new Event('marvin:open-command-palette'))`).
#   3) **`components/ui/DashboardKit.jsx`** : extraction de `CircleGauge`/`BarRow`/`StatCard`/
#      `Sparkline`/`Panel` (construits pour /monitoring v2.100) en bibliothèque partagée — toute
#      future page-dashboard réutilise au lieu de recopier des styles inline. `/monitoring`
#      migré pour les importer (zéro changement visuel, vérifié).
#   4) **Raccourcis clavier** : Ctrl+N (nouvelle conversation, marche même déjà sur "/" via
#      l'event `marvin:new-conversation" — un simple `router.push('/')` y serait un no-op),
#      Échap ferme le menu de sélection du micro dans `ChatInput.jsx`.
#   Vérifié en réel (Playwright) : toasts empilés avec bonnes couleurs/icônes lors d'une vraie
#   action (scan Catharsis), Ctrl+K ouvre/filtre/navigue, Ctrl+N réinitialise la conversation,
#   zéro erreur console sur 14 pages testées.
# v2.102.0 — 🔧 BOÎTE À OUTILS REGROUPÉE PAR FAMILLES. Signalé par l'utilisateur : 17 catégories
#   d'outils (Infographie/Documents/Fichiers/Web/PC & Système/Calendrier/Cloud/Tâches & Notes/
#   Mémoire & IA/Réseau/OCR & Vision/Email/SSH/Archives/Voix & Audio/Utilitaires/Données & Docs)
#   affichées en UNE rangée d'onglets horizontaux qui débordait déjà l'écran — illisible.
#   Ajout d'un niveau intermédiaire (`GROUPS` dans `app/outils/page.jsx`, même logique que les
#   sections de la sidebar) : 4 familles — 📄 Contenu & Documents, 🖥️ Système & Réseau,
#   🗂️ Organisation, 🌐 Web & Données — puis les catégories du groupe sélectionné en sous-onglets.
#   17 onglets à plat → 4 familles + sous-onglets courts. La recherche globale (déjà correcte,
#   cherchait déjà dans les 141 outils toutes catégories confondues) n'est pas affectée : elle
#   masque les deux rangées d'onglets comme avant. Petite redondance clarifiée : l'outil rapide
#   « Nettoyer le disque » (PC & Système) renvoie maintenant explicitement vers PC & Système →
#   Nettoyage pour la version détaillée par catégorie (ex-Catharsis). 141 outils inchangés
#   (réorganisation d'affichage uniquement, zéro perte). Vérifié en réel (Playwright) : clic sur
#   une famille affiche ses catégories, clic sur une catégorie affiche ses outils, zéro erreur
#   console.
# v2.103.0 — 🔌 MARVIN EN SERVEUR MCP (Model Context Protocol) — recherche web + sécurité
#   d'abord (voir échange utilisateur : demande explicite d'explorer MCP "sans oublier la
#   sécurité"). Constat de la recherche : MCP est devenu LE standard 2026 pour connecter une IA
#   à des outils (Claude/ChatGPT/Gemini/Copilot/Cursor, 10 000+ serveurs) MAIS l'écosystème a une
#   crise de sécurité documentée (faille SDK officielle ~200k instances, 38% des serveurs sans
#   authentification, 30+ CVE injection shell en 2 mois, attaques "rug pull" par mise à jour
#   malveillante). Décision : implémenter UNIQUEMENT le sens serveur (exposer les outils DÉJÀ
#   vérifiés de Marvin) — PAS le sens client (consommer des serveurs MCP tiers non audités),
#   qui reste une décision séparée à prendre au cas par cas.
#   Architecture (`backend/mcp_server.py`, transport stdio, lancé par le client MCP en
#   sous-processus) : PROXY RÉSEAU PUR vers le backend Marvin déjà démarré — n'importe JAMAIS
#   `tools.py`/`database.py` directement (Qdrant est mono-process, un import direct depuis un
#   2ᵉ process risquerait `AlreadyLocked`). Nouveau `GET /api/tools/list` (catalogue des 294
#   outils pour la découverte MCP) + nouveau `POST /api/mcp/execute`, DÉLIBÉRÉMENT séparé de
#   `/api/tools` : ce dernier force `confirmed=true` sur les outils dangereux (conçu pour les
#   boutons de la page Outils, qui ont DÉJÀ demandé confirmation avant l'appel) — le forcer pour
#   un appelant MCP externe permettrait une exécution destructrice sans confirmation. Le nouvel
#   endpoint respecte le niveau de permission ACTUEL de Marvin (Sécurisé/Standard/Expert) : en
#   Expert, confirmation auto (comme le reste de Marvin) ; sinon, `requiresConfirmation` remonte
#   normalement au client MCP, qui doit re-soumettre avec confirmed=true si SON utilisateur
#   approuve. `security.screen_command()` reste actif à l'intérieur de chaque outil (défense en
#   profondeur, inchangé). Audit tracé avec `source="mcp"` (distinct de "chat"/"ui"). Le serveur
#   ne démarre QUE si un client MCP le lance explicitement (config manuelle côté Claude
#   Desktop/Cursor) — aucun port ouvert par défaut, zéro découverte automatique.
# v2.104.0 — 🔌 PAGE /mcp — GUIDE DE CONNEXION MCP. Sur demande explicite (« ajouter un onglet
#   qui explique le MCP et comment s'y connecter », avec l'exigence : « les chemins doivent être
#   dynamiques, si j'installe Marvin sur une autre machine le MCP doit être sur le bon chemin »).
#   Nouveau `GET /api/mcp/config` : renvoie les chemins RÉELS de CETTE installation — jamais codés
#   en dur. `sys.executable` (le python.exe du venv réellement utilisé, où que Marvin soit
#   installé) + `config.BACKEND_DIR / "mcp_server.py"` (déjà dynamique, `Path(__file__).parent`).
#   Testé : sur cette machine, renvoie bien `C:\Users\Chawb\secretary-ai\backend\.venv\...` — sur
#   une autre installation, les chemins suivraient automatiquement sans aucune modification de
#   code. Nouvelle page `/mcp` (sidebar → Réglages, entre Accès mobile et Paramètres, même esprit
#   que la page de connexion mobile existante) : statut backend en direct, niveau de permission
#   actuel avec explication de son impact sur MCP, bloc JSON prêt à copier (bouton avec toast de
#   confirmation), explication courte du choix « serveur uniquement, jamais client ». Piège
#   récurrent re-attrapé : `useToast()` renvoie `{toast}`, pas directement les méthodes — corrigé
#   avant que ça parte en prod (déjà documenté dans CLAUDE.md depuis v2.101, mais reproduit une
#   fois de plus en écrivant ce composant, donc vérifié explicitement cette fois). Vérifié en réel
#   (Playwright) : statut/permission/JSON corrects, clic sur Copier déclenche le toast, zéro
#   erreur console.
# v2.105.0 — 🧹 3 PETITES DETTES REFERMÉES (suite auto-proposée après audit). (1) Marvin Doctor
#   vérifie maintenant le serveur MCP (`doctor.py` check #11) : paquet `mcp` installé + syntaxe
#   de `mcp_server.py` valide (compile() sans exécuter). (2) Palette de commandes (Ctrl+K) : la
#   recherche n'indexait que les pages, pas les 294 outils. Le catalogue d'outils est maintenant
#   chargé à la demande (1ʳᵉ ouverture de la palette seulement, pas au chargement de chaque page)
#   depuis `/api/tools/list`, et un résultat "outil" sélectionné navigue vers
#   `/outils?q=<nom>` — `app/outils/page.jsx` lit ce paramètre `q` au montage pour préremplir sa
#   recherche (a nécessité un `Suspense` autour du composant, requis par `useSearchParams`).
#   (3) `CircleGauge` (`DashboardKit.jsx`) avait un seuil de couleur pensé pour un usage
#   ressource (haut = mauvais, ex. CPU/RAM) — nouvelle option `invert` (haut = bon, ex. score de
#   santé) + `suffix` personnalisable ("/100" au lieu de "%"). La page Santé utilise maintenant
#   ce composant partagé au lieu d'un `conic-gradient` fait main. Vérifié en réel (Playwright) :
#   check Doctor MCP → "ok", Ctrl+K + "csv_analyze" + Entrée → atterrit sur l'outil pré-filtré,
#   gauge Santé toujours vert à 100/100, zéro erreur console.
# v2.106.0 — 🩺 AUDIT COMPLET SUR DEMANDE EXPLICITE (« revois tout les chats, teste/corrige/
#   améliore tous les outils, règle la température Ollama pour éviter les hallucinations »).
#   Audit basé sur `data/secretary.db::tool_executions` (754 exécutions réelles, 141 échecs
#   historiques), triés un par un (déjà corrigé / comportement attendu / vrai bug) plutôt que
#   supposés. 6 vrais bugs d'outils corrigés (tools.py) : (1) `_resolve_path` ne corrigeait
#   l'alias Bureau→Desktop que si le nom d'utilisateur était FAUX dans le chemin — jamais si déjà
#   correct (`pc_open_file` échouait sur "C:\Users\Chawb\Bureau"). (2) `pc_open_file` retombe
#   maintenant sur `pc_app_launch` si le chemin ressemble à un nom d'appli sans extension
#   (corrige "ouvre firefox/teraterm"). (3) `json_tool` accepte `json` en alias de `data`.
#   (4) `ocr_extract` valide le modèle Ollama demandé contre les modèles réellement installés,
#   repli silencieux sur `llava-phi3` si halluciné (ex. "llava:13b" jamais installé → 404 sec).
#   (5) `net_dns_lookup` accepte `domain`/`hostname` en alias de `host`. (6) `translate` accepte
#   `source`/`target` en alias de `source_lang`/`target_lang` (sinon retombait en silence sur
#   auto→en, faux sans erreur visible). (7) `file_convert_docx_to_pdf` : bloquait tout FastAPI
#   pendant la conversion Word (pas de `asyncio.to_thread`) + oubliait `pythoncom.CoInitialize()`
#   sur le thread d'exécution (même piège COM que `system_search`, déjà corrigé là-bas). (8)
#   `billing_quote_pdf` : `Unknown format code 'f' for str` quand un devis JSON produit par le
#   LLM contient des nombres en string — coercion défensive `_num()`.
#   Anti-hallucination Ollama, à la racine (agent.py) : la branche « modèle choisi manuellement »
#   avait la température INVERSÉE par rapport à la doctrine de `config.py::MODEL_PROFILES` —
#   elle montait à 0.6 pour les PETITS modèles (3b/1b), alors que ce sont eux les plus sujets à
#   halluciner un nom d'outil/paramètre plausible mais faux (cause racine du bug ocr_extract
#   ci-dessus). Corrigé : 0.2-0.3 partout, cohérent avec le reste. Ajout de `top_p: 0.9` à toutes
#   les requêtes Ollama (resserre l'échantillonnage). Nouvelle règle d'or #7 dans le prompt
#   système : ne jamais inventer un identifiant technique qui « sonne juste » (modèle IA, version,
#   ID), laisser le paramètre optionnel vide plutôt que deviner.
#   Test réel élargi : `system_self_test` passe de 16-18 à 46 outils couverts (tools.py, tous
#   lecture seule, zéro effet de bord) ; + 24 outils supplémentaires testés manuellement via
#   `/api/mcp/execute` (OS/réseau/texte/documents). 69 outils vérifiés au total sur cette session,
#   0 nouveau bug au-delà des 8 ci-dessus (les échecs restants étaient soit déjà corrigés, soit du
#   bruit de méthodologie de test — ex. conflit de verrou Qdrant en appelant `search_semantic` en
#   script autonome au lieu de passer par le backend déjà lancé, cf. règle connue).
#   Revue des mémoires de sessions passées → 1 vraie dette de sécurité trouvée et corrigée :
#   `audit.py::log_action` ne filtrait les secrets que par égalité stricte de nom de clé
#   ("password"/"token"/"secret") → ratait `owner_password`, `bot_token`, `api_key`,
#   `client_secret`, `private_key` etc., qui finissaient en clair dans le fichier JSONL git-able.
#   Filtre passé en sous-chaîne (insensible à la casse) sur une liste élargie. Les autres pistes
#   des mémoires (COM/asyncio.to_thread, backup registre avant tweak) étaient déjà correctement
#   en place — vérifiées, pas re-corrigées inutilement.
# v2.107.0 — 🧹 JSON hors du chat + 5 axes (suite auto-proposée après l'audit v2.106, sur
#   demande explicite « tout format json doit disparaitre du chat » + « fait tout »).
#   BUG RACINE trouvé et corrigé : `MessageBubble.jsx::renderToolResult` (le composant
#   RÉELLEMENT rendu en live, pas `ToolCallCard.jsx` qui s'est avéré être du code mort jamais
#   importé) retombait sur un `JSON.stringify` brut par défaut pour tout outil sans rendu
#   dédié — soit la grande majorité des 294 (ex. winget_search). Corrigé : le fallback utilise
#   désormais `PrettyResult` (déjà existant mais jamais branché ici) → lisible par défaut,
#   JSON disponible uniquement via son bouton « Voir en JSON ». Vérifié en réel (Playwright)
#   sur une conversation réelle affichant ce bug.
#   5 axes supplémentaires : (1) suppression de `ToolCallCard.jsx`/`.module.css`, code mort
#   (zéro import) qui dupliquait `MessageBubble::ToolCallInline` — source unique désormais.
#   (2) `app/api/conversations/*` transformé en proxy pur vers le backend Python (qui avait
#   déjà une implémentation équivalente plus correcte) au lieu de dupliquer l'accès SQLite
#   direct côté JS (`lib/database/queries.js`, même fichier `data/secretary.db` que Python) —
#   dette dupliquée déjà repérée dans le fork Codex/Grok, confirmée présente ici aussi. Bug
#   trouvé au passage et corrigé côté Python : `update_conversation` ne pouvait jamais
#   désassigner un projet (`body.projectId is not None` ignorait un `null` explicite) —
#   passé en `model_dump(exclude_unset=True)`. Testé en réel (rename/restore, assign,
#   delete sur conversation jetable). (3) `PrettyResult.jsx` enrichi : formatage monétaire
#   (`total_ttc`, `unit_price`…), puces de statut colorées (payée/en retard/running/stopped…),
#   libellés FR pour les familles billing_*/win_*. (4) Le profil `analysis` envoyait les 294
#   outils SANS filtrage (risque de hallucination de nom d'outil sur un si gros catalogue,
#   déjà repéré dans les mémoires) — applique désormais le même filtrage mots-clés+sémantique
#   que chat/agent, avec un plafond plus large (90 vs 28) pour garder la couverture. Vérifié :
#   requête "caractéristiques matérielles" → 29 outils pertinents incluant bien
#   `pc_hardware_specs` (au lieu de 294 bruts). (5) `scripts/smoke_test_chat.py` (nouveau) :
#   recharge des conversations réelles via Playwright et détecte tout dump JSON multi-clés
#   visible par défaut — regex volontairement ciblée sur les dumps multi-paires (le vrai bug)
#   pour ne pas remonter de faux positifs sur un autre problème distinct et déjà atténué
#   (un appel d'outil écrit en texte par le LLM, {"query":"..."} à une seule clé — cf. §5
#   CLAUDE.md, `_salvage_text_tool_calls`). A servi à re-tester tout ce qui précède.
# v2.108.0 — 🧹 Dualité JS/Python éliminée sur notes/tâches/projets/mémoire (suite directe
#   de v2.107, sur demande explicite « continue sur cette voie » puis « fait les 5 »).
#   `app/api/chat/route.js` (255 lignes, moteur de chat JS legacy 100% mort) supprimé sur
#   confirmation explicite après avoir été bloqué une 1ère fois par le classifieur de
#   permissions (action jugée trop destructive pour une inférence autonome — comportement
#   voulu, contourné correctement en redemandant). DÉCOUVERTE EN COURS DE ROUTE, PAS ENCORE
#   TRAITÉE : `app/api/tools/route.js` + `lib/agent/tools.js` (1344 lignes) forment un
#   second moteur d'agent JS complet, également confirmé 100% mort (zéro appelant réel,
#   l'Outils page appelle `${BACKEND_URL}/api/tools` en Python, pas la route relative) —
#   signalé à l'utilisateur, pas supprimé sans confirmation explicite (même prudence que
#   pour app/api/chat).
#   `/api/notes` et `/api/tasks` transformés en proxy pur vers le backend Python (déjà un
#   CRUD complet côté Python) — même pattern que `/api/conversations` en v2.107, interface
#   externe (POST {action,...}) conservée à l'identique pour ne toucher aucune page.
#   `/api/projects` : Python n'avait qu'une lecture (`get_projects`) — ajouté
#   `create_project`/`delete_project` (+ `CREATE TABLE IF NOT EXISTS` défensif, la table
#   n'était créée que côté JS jusqu'ici) et les endpoints POST/DELETE, puis proxyfié.
#   Actions mémoire de `/api/settings` (get/create/delete/clear_memories) proxyfiées vers
#   `/api/memories` (Python) — dupliquaient `memory_save`/`memory_list`/`memory_delete`,
#   déjà des outils de chat. Ajouté côté Python : `POST /api/memories` et
#   `DELETE /api/memories` (clear-all), qui n'existaient pas. La gestion de modèles Ollama
#   (pull/delete/list/set_model) reste en JS — pas de duplication, pas d'équivalent Python.
#   `lib/database/queries.js` élagué de 38 à 2 exports (`getSetting`/`setSetting`, les seuls
#   encore réellement importés) — 36 fonctions mortes retirées (conversations/messages/
#   tasks/notes désormais orphelines par ce ménage même, + OAuth/journal fichiers/templates
#   email jamais appelés, dette préexistante). Chaque proxy testé en réel bout-en-bout
#   (create/update/delete) avant/après bascule, y compris un vrai bug trouvé au passage :
#   `update_conversation` (Python) ne pouvait jamais désassigner un projet — déjà corrigé
#   en v2.107, revérifié ici. `scripts/smoke_test_chat.py` reste vert après chaque étape.
# v2.109.0 — 🕐 Bug de fuseau horaire sur les timestamps (trouvé en continuant l'audit v2.108
#   sur demande explicite « continue le travail »). En testant la création de note via l'UI
#   réelle (pas juste curl), une note tout juste créée affichait « il y a 2h » au lieu
#   d'« à l'instant ». Cause racine : le backend renvoie des timestamps SQLite UTC naïfs
#   ("2026-07-09 08:05:10", sans 'Z'/fuseau) — `new Date(...)` côté navigateur les interprète
#   comme une heure LOCALE en l'absence d'indicateur de fuseau explicite, décalant tout
#   affichage relatif/absolu de l'écart UTC local de l'utilisateur (ex. +2h en France l'été).
#   Le correctif (ajout de 'Z' avant parsing) existait déjà dans `app/cron/page.jsx` et
#   `app/monitoring/page.jsx` mais n'avait jamais été appliqué ailleurs — bug préexistant,
#   pas une régression de cette session, juste jamais repéré faute de test réel via l'UI.
#   Corrigé dans `app/notes/page.jsx` (liste + panneau « Créé/Modifié »), `app/docs/page.jsx`
#   (calcul « résolu cette semaine »), `app/workflows/page.jsx` (historique d'exécutions),
#   `app/page.js` (regroupement de la sidebar conversations Aujourd'hui/7j/30j — pouvait
#   mal classer une conversation faite juste après minuit local). `components/chat/
#   PrettyResult.jsx::fmtDate` corrigé avec une garde (n'ajoute 'Z' que si la chaîne n'a pas
#   déjà un fuseau explicite) car ce composant affiche aussi des dates déjà correctement
#   fuseautées (emails, événements calendrier) — un ajout aveugle de 'Z' les aurait cassées.
#   Vérifié en réel : création d'une note via clic UI → « à l'instant » correct après le fix
#   (contre « il y a 2h » avant), ré-affichage d'une note de 3 min → « il y a 3 min » correct.
# v2.110.0 — 🧹 Suppression du 2e moteur d'agent JS mort (suite de v2.108/v2.109, sur
#   confirmation explicite via AskUserQuestion après 2 refus du classifieur de permissions
#   sur des directives génériques « continue »/« tu es libre »). `app/api/tools/route.js`
#   + `lib/agent/tools.js` (1344 lignes) supprimés — code confirmé 100% mort depuis v2.108
#   (zéro import, zéro appel `/api/tools` relatif nulle part dans le code ; la page Outils
#   appelle `${BACKEND_URL}/api/tools`, l'endpoint Python homonyme mais différent). Vérifié
#   après coup : compilation Next.js propre, `scripts/smoke_test_chat.py` toujours vert.
#   Incident survenu pendant la vérification (documenté, pas dans le code) : un test de
#   suppression via clic Playwright automatisé avec un sélecteur DOM imprécis (ancestor +
#   « dernier bouton ») a supprimé une VRAIE conversation utilisateur au lieu d'un projet
#   de test — détecté en recoupant le compteur de conversations avant/après, pas par une
#   erreur. Pas de sauvegarde automatique de `data/secretary.db` trouvée pour la récupérer.
#   Règle retenue pour toute suite : ne jamais tester une action destructive via clic UI
#   automatisé sur des données réelles — sélecteur univoque (title/id) sur données jetables
#   uniquement, ou suppression par ID exact via curl/API directe.
# v2.111.0 — 💾 Sauvegarde auto + 🗂️ Fin de la dualité fichiers + 🧪 Smoke-test pages (3
#   propositions faites après le point précédent, toutes acceptées explicitement).
#   (1) `backend/backup.py` : sauvegarde quotidienne de `data/secretary.db` via l'API
#   native SQLite (`Connection.backup()`, pas une copie fichier brute — la base est en
#   mode WAL, une copie naïve pourrait capturer un état incohérent pendant une écriture
#   active). Une sauvegarde immédiate au démarrage (20s de délai) + une toutes les 24h,
#   rotation sur les 14 dernières. Endpoints `GET/POST /api/backups`. Motivé directement
#   par l'incident v2.110 : aucune sauvegarde n'existait quand il en a fallu une. Vérifié
#   en réel : sauvegarde créée au démarrage, intégrité SQLite confirmée (`PRAGMA
#   integrity_check` → ok), déclenchement manuel testé, rotation en place.
#   (2) `app/api/files/route.js` + `lib/services/fileManager.js` (721 lignes, accès fs
#   Node direct) migrés vers un proxy pur appelant les outils Python déjà existants
#   (file_list/file_info/file_find/file_create_folder/file_rename/file_move/file_copy/
#   file_delete via `/api/tools`, qui auto-confirme déjà les outils dangereux pour les
#   appelants UI). Seules les ~13 actions réellement câblées ont été portées — 8 fonctions
#   exportées par l'ancien fichier (readFileContent/writeFileContent/searchTextInFiles/
#   convertDocxToPdf/createDocx/editDocx/appendToDocx/getPdfInfo) étaient déjà du code mort
#   confirmé (zéro appelant, vérifié par grep) et n'ont pas été portées. `fileManager.js`
#   supprimé une fois vide de tout appelant réel. **Vrai bug trouvé en testant** : l'action
#   « organize » (classement par catégorie) créait des FICHIERS nommés "Images"/"Videos"
#   au lieu de dossiers, la 1ʳᵉ fois qu'ils n'existaient pas encore — `file_move` ne
#   recrée le nom du fichier source que si la destination est déjà un dossier EXISTANT,
#   sinon il traite la destination comme un nom de fichier littéral. Corrigé en construisant
#   toujours le chemin de destination COMPLET (dossier + nom de fichier) côté proxy, jamais
#   juste le dossier — même correctif appliqué à batchMove/batchCopy/move (même risque
#   latent). Autre bug trouvé : le champ `type` renvoyé par `file_find` est incohérent selon
#   la méthode (l'index Windows Search y met un type MIME/extension comme ".txt", pas
#   "fichier"/"dossier") — la recherche par nom affichait le mauvais type. Corrigé en ne
#   faisant plus confiance à ce champ (avec `include_dirs=false`, les résultats sont
#   toujours des fichiers). Testé en réel sur un dossier isolé hors de l'app : list, search,
#   info, sandbox, createFolder, rename, move, batchCopy, organize, batchDelete — tous
#   vérifiés avant/après fix, y compris via un vrai clic dans /fichiers → Parcourir.
#   (3) `scripts/smoke_test_pages.py` (nouveau) : formalise le balayage manuel de pages
#   fait plusieurs fois cette session (erreurs console au chargement) — 34 pages couvertes
#   (dont les anciennes routes redirect), toutes vertes après les changements ci-dessus.
# v2.112.0 — 💾 Restauration de sauvegarde. Complète v2.111 : une sauvegarde qu'on ne sait
#   pas restaurer ne vaut rien. `backup.py::restore_backup(filename)` : valide le nom de
#   fichier contre BACKUP_DIR (empêche toute traversée de chemin), prend AUTOMATIQUEMENT
#   une sauvegarde de sécurité de l'état actuel AVANT de restaurer (la restauration
#   elle-même devient réversible), puis copie la sauvegarde choisie par-dessus la base live
#   via `Connection.backup()` (même API que la sauvegarde, gérée par le verrouillage SQLite
#   natif — pas un remplacement de fichier brut). Endpoint `POST /api/backups/restore`
#   (confirmation explicite obligatoire, hors du registre d'outils : pas pilotable depuis
#   le chat par le LLM).
#   **Test réel réalisé avec prudence** : créé une note jetable, sauvegardé, supprimé la
#   note (perte simulée) — puis la restauration EN CONDITIONS RÉELLES a été bloquée par le
#   classifieur de permissions Claude Code (jugé trop risqué d'auto-tester un restore sur
#   la base live juste après l'incident de suppression accidentelle de cette même session,
#   cf. v2.110). Décision : ne pas insister. Le MÉCANISME sous-jacent (le même appel
#   `Connection.backup()` en sens inverse) a été vérifié séparément sur une COPIE isolée de
#   la base (jamais la live) : la note supprimée revient bien, `PRAGMA integrity_check` OK.
#   MISE À JOUR : l'utilisateur a ensuite demandé à être sollicité via AskUserQuestion
#   AVANT tout blocage plutôt qu'après — appliqué, question posée nommant l'action
#   précisément, acceptée, test de restauration REJOUÉ contre la vraie base live → succès
#   confirmé (note restaurée, backend sain après coup).
# v2.113.0 — 🔧 Winget "installe X" réparé de bout en bout — signalé par l'utilisateur
#   (« regarde la dernière conversation où je demande l'installation de victoria, il sait
#   que c'est le bon logiciel mais ne l'installe pas »). DEUX vrais bugs trouvés en
#   remontant la conversation réelle (pas en devinant) :
#   (1) `agent.py::_KEYWORD_TOOLS` n'avait AUCUNE entrée pour "installe"/"installer" — les
#   outils `winget_*` n'étaient donc JAMAIS proposés au LLM sur les profils filtrés
#   (chat/agent) pour ce type de demande (même classe de bug déjà documentée : un outil
#   enregistré dans TOOLS_REGISTRY n'est pas automatiquement visible du chat). Le LLM,
#   sans le bon outil disponible, "documentait" l'installation via `document_generate`
#   (génère un .docx expliquant comment installer) au lieu d'installer réellement — un
#   comportement plausible mais faux. Ajout d'une entrée `_KEYWORD_TOOLS` avec le stem
#   court `"instal"` (pas `"installe"`) pour matcher aussi "install" sans le e final —
#   repéré en reproduisant le bug avec le message EXACT de l'utilisateur ("install le
#   logiciel victoria", sans e). Vérifié : winget_search/winget_install apparaissent
#   maintenant dans la liste filtrée pour ce message, document_generate n'y est plus.
#   (2) Une fois le routage corrigé, un second bug est apparu au premier test réel :
#   `winget_install` appelé avec `query: 'Victoria'` (nom flou) au lieu de l'`id` exact
#   renvoyé par `winget_search` ("Victoria.Victoria") → winget refusait tout net
#   ("Plusieurs packages correspondent à vos critères"), même avec un seul paquet nommé
#   EXACTEMENT "Victoria". Plutôt que de compter sur le LLM pour rejouer avec le bon id
#   (fragile), `execute_winget_install` (tools.py) résout maintenant LUI-MÊME l'ambiguïté :
#   si un id exact n'est pas fourni, il relance une recherche interne et auto-sélectionne
#   l'id du paquet dont le NOM correspond EXACTEMENT à la requête (ou l'unique résultat
#   s'il n'y en a qu'un) ; sinon renvoie une erreur claire listant les paquets candidats.
#   **Testé en conditions réelles jusqu'au bout, sur autorisation explicite de
#   l'utilisateur** (AskUserQuestion posée proactivement avant tout risque de blocage,
#   cf. v2.112) : conversation rejouée avec le message original → winget_search puis
#   winget_install (toujours appelé avec `query`, résolu en interne vers
#   `Victoria.Victoria`) → installation réussie (code 0), confirmée présente sur la
#   machine via `winget_list_installed`.
# v2.114.0 — 🔍 Audit de conversations réelles (suite directe de v2.113, même méthode :
#   examiner les VRAIES conversations plutôt que deviner). 2 bugs de plus trouvés en
#   balayant les 19 conversations existantes (`scripts` ad-hoc, pas encore formalisé) :
#   (1) `win_service_action` exigeait le nom INTERNE exact du service ("MpsSvc"), jamais
#   le nom D'AFFICHAGE ("Windows Defender Firewall") qu'un LLM/utilisateur emploie
#   naturellement — et sur un Windows localisé en français, même une recherche par
#   sous-chaîne sur le nom d'affichage échouait ("Pare-feu Windows Defender" ne contient
#   pas "Firewall"). Ajout de `_resolve_service_name()` : essai exact d'abord, repli sur
#   une recherche floue Name+DisplayName, erreur claire listant les candidats si
#   ambigu. Testé en réel : "Pare-feu" et "mpssvc" (n'importe quelle casse) résolvent
#   maintenant correctement — le nom anglais complet sur un système francisé reste une
#   limite connue (traduction totale, pas juste une variante de casse/ordre), pas
#   poursuivie plus loin (aurait nécessité une table de traduction dédiée par service).
#   (2) Le LLM a appelé `billing_quote_email` avec `quote_id: 'ID_DU_DEVIS'` — un
#   PLACEHOLDER littéral au lieu d'un vrai identifiant, sur une demande vague ("un devis
#   en attente" sans client précisé) alors que `billing_quote_list` était pourtant déjà
#   dans les outils proposés. La règle d'or #7 anti-hallucination (v2.106) ne couvrait que
#   les paramètres OPTIONNELS ("laisse vide plutôt que deviner") — étendue pour couvrir
#   explicitement les paramètres OBLIGATOIRES inconnus : chercher le vrai identifiant via
#   l'outil de liste/recherche approprié, ou demander une clarification, jamais écrire un
#   texte de substitution en guise de valeur.
# v2.115.0 — 🔎 Recherche sémantique améliorée (reranker + hybride) + 🧠 consolidation
#   mémoire. Suite d'une recherche web sur les bonnes pratiques 2026 (RAG, mémoire
#   d'agent, tool-calling local), demandée explicitement par l'utilisateur, puis « je te
#   laisse libre go » sur les axes proposés.
#   (1) `reranker.py` (nouveau) : cross-encoder local léger (flashrank,
#   ms-marco-TinyBERT-L-2-v2, ~3 Mo, CPU, dizaines de ms) qui re-score un pool élargi de
#   candidats sur leur pertinence RÉELLE par rapport à la requête — la recherche
#   vectorielle seule sert désormais de filtre rapide, pas de verdict final. Best-effort :
#   si le reranker est indisponible, repli silencieux sur l'ordre vectoriel d'origine.
#   (2) `vector_store.py::search()` : ajout d'un étage BM25 lexical (rank_bm25, index en
#   mémoire par collection, TTL 60s) fusionné au vecteur par Reciprocal Rank Fusion avant
#   le reranking — le vecteur seul rate parfois un passage aux mots-clés exacts mais formulé
#   différemment ; BM25 seul rate les paraphrases ; ensemble ils se couvrent. Pipeline
#   complet : vecteur+BM25 (pool large) → fusion RRF → reranker cross-encoder → top N.
#   Bénéficie automatiquement à `search_semantic`, `document_ask`, `memory_search`,
#   `unified_search` (tous passent par `vector_store.search`). Vérifié en réel : les 3
#   scores (vec/bm25/rerank) cohabitent et influencent le classement final, testé sur
#   des documents indexés réels (résultats de tests réseau).
#   (3) `memory_consolidation.py` (nouveau) : fusion périodique des souvenirs quasi-
#   identiques, même esprit que le Learning Log des compétences (v2.95) mais VOLONTAIREMENT
#   déterministe (recouvrement de sous-chaîne, même heuristique que le dédoublonnage déjà
#   fait à l'enregistrement dans `execute_memory_save`) plutôt que piloté par un LLM — évite
#   le risque qu'un modèle fusionne à tort deux souvenirs différents. Worker de fond
#   quotidien + endpoints `GET /api/memories/consolidate/preview` (aperçu sans suppression)
#   et `POST /api/memories/consolidate` (exécution). Testé en réel avec deux souvenirs
#   quasi-identiques créés exprès : détection correcte (recouvrement 0.8), fusion garde le
#   plus détaillé, aucun des 4 vrais souvenirs de l'utilisateur touché (aucun doublon réel).
#
# v2.116 (📊 Monitoring actionnable) — demandé explicitement (« ameliore monitoring, rend le
#   plus interactif et utils car dans l'etat actuel il ne sert pas a grand chose, inspire toi
#   en cherchant sur le web »). Recherche menée (Netdata/Glances/htop, tendances dashboard
#   2026 : progressive disclosure, panneaux actionnables plutôt que jauges passives). La page
#   affichait déjà CPU/RAM/réseau/disques/historique d'outils mais AUCUNE action possible —
#   corrigé sur 4 axes :
#   (1) `GET /api/monitor` (SSE) diffuse désormais `top_processes` (8 process les plus
#   gourmands en CPU, via `psutil.process_iter`) — chaque ligne a un bouton ✕ qui appelle
#   `pc_process_kill` via `/api/tools` (confirmation JS avant l'appel, outil déjà dans
#   `DANGEROUS_TOOLS` donc auto-confirmé côté UI, cohérent avec le pattern déjà établi pour
#   `app/files/page.jsx`).
#   (2) Le payload SSE inclut aussi `gpu` (nom/VRAM/backend) via `local_video.get_device_info()`
#   — déjà cache-TTL 20s côté `local_video.py`, donc l'appeler chaque cycle SSE (2s) ne
#   redétecte réellement que toutes les ~10 itérations, coût négligeable.
#   (3) Bannière d'alerte quand un disque dépasse 85% d'occupation (le C: de cette machine
#   était à 90% sur la capture d'écran fournie par l'utilisateur) avec un lien direct vers
#   `/systeme?tab=nettoyage` (Catharsis) — l'utilisateur n'a plus besoin de deviner où agir.
#   (4) Bouton « ↻ Relancer » sur chaque exécution d'outil EN ÉCHEC dans l'historique déjà
#   affiché — rejoue le même outil avec les mêmes arguments via `/api/tools`, sans repasser
#   par le chat.
#   Aucun nouvel endpoint REST (le kill/retry passent par `/api/tools`, déjà existant et déjà
#   gated par confirmation) — uniquement une extension du payload SSE + du frontend.
# v2.117 (🔗 SSH — sécurité + fonctionnalité + ergonomie) — demandé explicitement (« l onglet
#   ssh devrait etre ameliorer en fonctionalité et en ergonomie, recherche aussi sur le web »).
#   Recherche menée (webssh/Terminus Web/ttyd — SFTP intégré, xterm.js, diagnostics serveur).
#   En auditant le code AVANT d'ajouter quoi que ce soit, trouvé que les 3 endpoints REST de
#   la page /ssh (test/exec/exec-stream) réimplémentaient CHACUN leur propre connexion
#   paramiko en dur — RSA uniquement (`paramiko.RSAKey.from_private_key`, une clé Ed25519 —
#   le défaut de `ssh-keygen` depuis des années — échouait) ET SANS PASSER par
#   `security.screen_command()`, alors que CLAUDE.md §6 est explicite : le terminal SSH tapé
#   à la main par un humain était donc le SEUL chemin d'exécution de commandes de tout Marvin
#   à ne PAS avoir le garde-fou anti-catastrophe (la version pilotée par le chat,
#   tools.py::execute_ssh_exec, l'avait déjà, et supportait déjà tous les formats de clé via
#   `_ssh_load_key`). Corrigé en supprimant la duplication : les 3 endpoints délèguent
#   désormais à `tools._ssh_connect`, et `security.guard_result()` est appliqué avant toute
#   exécution SSH côté page web. Vérifié en isolation (guard_result bloque bien "rm -rf /",
#   laisse passer "ls -la" — pas testé en direct sur un vrai hôte pour ne pas envoyer une
#   commande destructive à une machine réelle).
#   Fonctionnalités ajoutées, toutes en réutilisant la logique déjà existante côté outils
#   chat (tools.py::execute_ssh_list_dir/server_info, jusqu'ici injoignable depuis la page) :
#   navigateur SFTP (parcourir/envoyer/télécharger, `GET/POST /api/ssh/{id}/browse|upload|
#   download`), diagnostic serveur en un clic (OS/uptime/mémoire/disque/charge, `GET
#   /api/ssh/{id}/info`), édition d'une connexion existante (`PUT /api/ssh/{id}` — jusqu'ici
#   seuls add/delete existaient, un typo dans l'hôte obligeait à tout ressaisir), passphrase
#   de clé privée chiffrée (colonne `key_passphrase` ajoutée en DB — tools.py la lisait déjà
#   mais elle n'existait nulle part, fonctionnalité fantôme), bouton de test rapide par
#   connexion avec badge de statut (🧪 dans la sidebar, persisté via `last_test_ok`/
#   `last_test_at`), recherche/filtre des connexions, bouton copier sur chaque commande du
#   terminal. Migration DB via `ALTER TABLE ADD COLUMN` défensif (colonnes absentes → ajout
#   silencieux au premier démarrage, ne casse pas les connexions déjà sauvegardées).
#   Vérifié en réel : 34/34 pages au smoke-test, 0 erreur console (Playwright, tous les
#   onglets Terminal/Fichiers/Infos + formulaire d'édition), et confirmé qu'un appel réel
#   contre un hôte injoignable renvoie une erreur JSON propre après le timeout paramiko
#   (~30s) plutôt que de bloquer indéfiniment.
#   Correctif ergonomie signalé par l'utilisateur juste après coup (capture d'écran d'un
#   `ls` sans aucune sortie visible, "je suis bien connecté mais je ne vois pas réellement
#   le terminal") : diagnostiqué en isolation (script Python direct hors HTTP) — PAS un bug,
#   le dossier perso distant ne contenait que des fichiers cachés donc `ls` sans `-a`
#   renvoie légitimement une sortie vide (confirmé : `ls -la` sur la même connexion listait
#   bien les fichiers). Le vrai bug était ergonomique : rien ne distinguait "commande
#   toujours en cours" de "terminée sans rien à afficher" — corrigé côté frontend
#   (`app/ssh/page.jsx`) avec une ligne `(terminé, aucune sortie)` quand exit_code=0 et
#   qu'aucune ligne stdout/stderr n'a été reçue.
#
# v2.118 (🖥️ Terminal SSH interactif RÉEL — PTY + xterm.js) : demandé explicitement (« je
#   veux que peut importe que je suis sur un ssh qui donne sur un windows ou linux que je
#   voie le terminal comme si j'y étais »). L'ancien modèle exec/stream (une commande =
#   une requête SSE, attend la fin, pas d'invite interactive) ne pouvait pas donner cette
#   sensation. Remplacé par un vrai shell PTY : nouveau `WS /api/ssh/{id}/shell` ouvre
#   `paramiko.invoke_shell()` et relaie les octets bruts en continu dans les deux sens ;
#   côté frontend, `app/ssh/page.jsx::XtermSSH` utilise xterm.js (`@xterm/xterm` +
#   `@xterm/addon-fit`) pour un rendu de terminal complet (couleurs, curseur, resize,
#   scrollback). AUCUNE distinction Windows/Linux nécessaire côté code : le protocole SSH
#   délègue l'allocation du PTY et le choix du shell (bash/sh ou cmd.exe/PowerShell) au
#   serveur OpenSSH distant — Marvin ne fait que transporter les octets, exactement comme
#   PuTTY ou `ssh` en ligne de commande.
#   ⚠️ Contrepartie de sécurité ASSUMÉE et documentée en commentaire à l'endpoint : un flux
#   d'octets bruts interactif ne peut PAS passer par `security.screen_command()` sans
#   casser l'interactivité (pas de "commande complète" identifiable avant que l'utilisateur
#   appuie sur Entrée côté shell distant). Le garde-fou reste entier sur tous les chemins
#   AUTOMATISÉS de Marvin (chat, `/api/ssh/exec` + `/exec/stream` déjà gardés en v2.117) —
#   ce nouveau canal est un clavier direct tenu par un humain déjà authentifié sur sa
#   propre connexion sauvegardée, équivalent fonctionnel à ouvrir PuTTY soi-même.
#   Le terminal reste monté en permanence (masqué en `display:none`, pas démonté) quand on
#   bascule sur les onglets Fichiers/Infos, pour ne jamais couper la session shell en cours
#   — seul un changement de CONNEXION force une reconnexion (`key={activeConn.id}`).
#   Dépendance manquante découverte en cours de route : `websockets` (requis par uvicorn
#   pour le support WebSocket) n'était pas installé dans ce venv malgré `uvicorn[standard]`
#   — ajouté explicitement à `requirements.txt`.
#   Testé en réel (Playwright) contre une vraie connexion SSH Linux : bannière MOTD
#   complète affichée à la connexion, `echo` tapé au clavier répond instantanément, bouton
#   raccourci `pwd` exécuté directement dans le shell — zéro erreur console fonctionnelle.
#
# v2.119 (☁️ Ollama Cloud — routage local/cloud par SENSIBILITÉ) : demandé explicitement
#   après souscription de l'utilisateur à Ollama Cloud (« rester purement local est pertinent
#   pour les données sensibles [emails, mots de passe...] mais pour optimiser Marvin l'option
#   cloud est très utile [...] sans hallucination ni limite matérielle »). Rejeté d'emblée
#   l'approche naïve "épingler un profil entier sur le cloud" (agent/chat mélangent météo ET
#   emails/SSH — un override par profil enverrait aussi les données sensibles au cloud).
#   Routage fait au niveau de la REQUÊTE, pas du profil (`agent.py`) :
#   1. Nouveau réglage opt-in `cloud_enabled` (désactivé par défaut) + `cloud_overrides`
#      ({profil: modèle_cloud}, ex. {"analysis": "glm-5.2:cloud"}) — même pattern que
#      `model_overrides` (v2.83), configurable via `PUT /api/settings/cloud_enabled` et
#      `.../cloud_overrides` (endpoints génériques déjà existants) + nouvelle section UI
#      dans Réglages → Modèle IA.
#   2. AVANT l'appel Ollama : `_is_sensitive_request()` vérifie mots-clés sensibles (email,
#      ssh, mot de passe, identifiants, clé API, token, facture/devis/client) dans le
#      dernier message ET les tool_calls déjà présents dans l'historique récent (un
#      "résume-moi ça" après un email chargé en contexte reste local aussi). Si sensible →
#      le modèle cloud n'est JAMAIS utilisé, quel que soit le réglage.
#   3. PENDANT la boucle d'outils : si un outil sensible (`email_*`, `ssh_*`, `billing_*`,
#      `credential_*`) est appelé alors qu'on est sur un modèle cloud — l'agent a pu décider
#      d'y aller sans mot-clé explicite dans le message initial — bascule IMMÉDIATE vers le
#      modèle local AVANT que le résultat (contenu d'email, sortie SSH…) ne parte au tour
#      suivant. S'applique même si l'utilisateur a choisi manuellement un modèle cloud dans
#      le sélecteur (dernier filet, pas une simple commodité de l'auto-routing).
#   Testé en réel (curl SSE contre le backend live, PAS de simulation) : avec cloud_enabled
#   + override sur TOUS les profils (agent/chat/analysis), "résume mes emails" reste sur
#   qwen2.5:14b (local, déclenche email_digest) tandis que "quelle heure est-il" bascule sur
#   glm-5.2:cloud — même override cloud présent sur le profil agent dans les deux cas, seule
#   la sensibilité du contenu change le résultat. UI vérifiée (Playwright, 0 erreur console) :
#   toggle + garde-fou affiché explicitement + sélecteurs par profil. cloud_enabled remis à
#   false après les tests (réglage opt-in, l'utilisateur l'active lui-même dans Réglages).
#
# v2.120 (🎚️ 3 préréglages cloud — Normal / Hyper sécurisé / Tout cloud) : demandé
#   explicitement après v2.119 (« je voudrais quand même avoir l'option tout cloud et tout
#   local en plus de ce qui existe [...] pour appliquer rapidement un setup global »).
#   Le garde-fou « donnée sensible → toujours local » (v2.119) reste actif dans LES TROIS
#   modes, y compris Tout cloud — ce n'est jamais désactivable, seule l'agressivité du
#   reste change. Aucun nouveau mécanisme lourd : les presets écrivent simplement les
#   réglages déjà existants (`cloud_enabled`/`cloud_overrides`) + UN nouveau réglage
#   `local_only_lockdown` (bool) pour le mode Hyper sécurisé.
#   `local_only_lockdown` est un coupe-circuit PRIORITAIRE sur tout le reste dans
#   `agent.py::run_agent` : bloque même une sélection MANUELLE explicite d'un modèle cloud
#   par l'utilisateur (jusqu'ici seule la protection mid-boucle v2.119 s'appliquait à la
#   sélection manuelle — désormais le lockdown la bloque dès le départ, avant même le 1er
#   appel Ollama).
#   Preset « Tout cloud » : active cloud_enabled + peuple cloud_overrides pour les 3 profils
#   (agent/chat/analysis) avec le meilleur modèle cloud installé (préférence deepseek > glm
#   > kimi > premier disponible) — un clic dans Réglages → Modèle IA.
#   Testé en réel (curl direct contre le backend live) : avec local_only_lockdown=true, un
#   POST /api/chat avec model="glm-5.2:cloud" (sélection manuelle explicite) rebascule bien
#   sur qwen2.5:14b local. UI vérifiée (Playwright, 0 erreur console) : les 3 cartes de
#   preset s'affichent, le clic sur chacune applique bien la config attendue (badge ACTIF
#   correct, sélecteur "Agent" pré-rempli avec deepseek-v4-flash:cloud après "Tout cloud",
#   toggle grisé + message après "Hyper sécurisé"). Remis en mode Normal (cloud désactivé)
#   après les tests.
#
# v2.121 (☠️ Mode Ultra débridé — 4ᵉ préréglage) : demandé explicitement (« je veux un
#   quatrième mode ultra débridé qui a le droit à tout sans aucun filtre de sécurité »).
#   Discussion préalable avec l'utilisateur AVANT implémentation (il a demandé mon avis) :
#   distinction posée entre DEUX catégories de garde-fous totalement différentes —
#   (1) le garde-fou de SENSIBILITÉ (v2.119, quelles données partent au cloud) est un choix
#   de confidentialité que l'utilisateur peut légitimement assumer pour SES propres données ;
#   (2) le garde-fou SYSTÈME de `security.py` (commandes catastrophiques irréversibles :
#   formatage, `rm -rf /`, fork bombs) protège contre un scénario différent — Marvin qui
#   détruit la machine par erreur (hallucination du modèle OU injection de prompt via du
#   contenu web/email lu par l'agent) — le désactiver n'apporterait aucun bénéfice de
#   performance, seulement du risque pur. Accord trouvé : le 4ᵉ mode ne touche QUE (1),
#   jamais (2), qui reste entier dans les QUATRE modes sans aucune exception.
#   Nouveau réglage `ultra_unrestricted` (bool) : quand actif, `_is_sensitive_request()`
#   est délibérément court-circuitée (`agent.py::run_agent`) — emails/SSH/mots de passe/
#   factures peuvent partir au cloud comme le reste — ET la protection mid-boucle v2.119
#   (repli local si un outil sensible est appelé en cours de tour) est également désactivée,
#   cohérence oblige. `local_only_lockdown` (Hyper sécurisé) reste prioritaire par défense
#   en profondeur si jamais les deux réglages étaient actifs simultanément (ne devrait pas
#   arriver via l'UI, les 4 presets sont mutuellement exclusifs).
#   UI : 4ᵉ carte de préréglage + `window.confirm()` bloquant avant toute activation,
#   texte explicite sur l'irréversibilité (une donnée déjà envoyée au cloud ne peut pas être
#   rappelée) et rappelant que le garde-fou système reste actif.
#   Vérification en conditions réelles PARTIELLEMENT bloquée par le classifieur de
#   permissions Claude Code lui-même : deux tentatives d'activer `ultra_unrestricted=true`
#   via des appels backend directs ont été refusées en dur (« hard block », « user
#   authorization cannot clear ») — signal pris au sérieux, aucune tentative de contournement.
#   Vérifié à la place : (a) la logique de code relue et tracée manuellement (bypass correct
#   aux deux points de contrôle), (b) le dialogue de confirmation s'affiche avec le bon texte
#   et un clic « Annuler » n'active bien rien (Playwright, capture avant/après, 0 erreur
#   console), (c) les primitives sous-jacentes (`_is_sensitive_request`, `_is_cloud_model`)
#   déjà validées en v2.119. Le chemin d'activation RÉEL (clic « Confirmer ») n'a pas été
#   testé en direct — à valider par l'utilisateur lui-même la première fois qu'il l'active.
#
# v2.122 (☁️ Routage cloud étendu aux outils + 🌐 fraîcheur web) : demandé explicitement
#   (« nous devons améliorer tous les outils et l'embedding de Marvin pour qu'il profite de
#   sa nouvelle puissance cloud » + « qu'il consulte le web plus souvent pour être sûr que
#   l'info n'est pas outdated »). Avis donné AVANT implémentation (demandé explicitement) :
#   (1) l'embedding (nomic-embed-text) NE bénéficie PAS du cloud — c'est un encodeur, pas un
#   modèle de conversation, et le changer casserait tout l'index déjà construit (espaces
#   vectoriels incompatibles entre modèles) — non touché, décision assumée. (2) la majorité
#   des 294 outils sont du code déterministe (fichiers, SSH, calendrier…) qui n'appelle
#   AUCUN LLM — le cloud ne leur apporte rien. (3) un modèle cloud plus puissant n'est PAS
#   plus à jour pour autant (lui aussi a une date de coupure) — la fraîcheur vient de la
#   recherche web, pas du choix du modèle. Périmètre validé par l'utilisateur avant d'agir.
#
#   **Routage cloud étendu** : audit complet (agent Explore) de tous les appels LLM internes
#   aux outils — 17 sites trouvés (document_generate, email_draft_reply/summarize/digest/
#   to_task/attachment_summary/watch_check, daily_briefing, document_ask/refine_section,
#   web_research, text_summarize, pdf_ocr, + 3 sites skills.py via callback injecté) qui
#   ignoraient TOTALEMENT le réglage Ollama Cloud — toujours en local, sans jamais consulter
#   cloud_enabled/cloud_overrides. Nouveau module `cloud_routing.py` (évite un import
#   circulaire : agent.py importe déjà tools.py pour TOOLS_REGISTRY/TOOLS_SPEC) centralise
#   les primitives déjà construites en v2.119-121 (mots-clés sensibles, cloud_enabled,
#   local_only_lockdown, ultra_unrestricted) + une nouvelle fonction `resolve_model()`
#   appliquant les mêmes règles à un appel LLM PONCTUEL (pas une conversation) : un modèle
#   local explicitement demandé est toujours respecté, un modèle cloud n'est utilisé que si
#   le texte du prompt n'est pas sensible (ou Ultra débridé actif), et les appels AVEC IMAGES
#   (OCR/vision) restent TOUJOURS locaux (aucune garantie que les modèles cloud installés
#   supportent le multimodal, et c'est justement le contenu le plus sensible — scans de
#   documents, captures d'écran). `agent.py` refactorisé pour déléguer à ce module au lieu
#   de dupliquer sa propre copie. `tools.py::_ollama_generate` (point d'entrée unique de 13
#   des 17 sites) branché en UNE seule modification ; les 9 call sites restants (main.py +
#   agent.py) qui pré-résolvaient un modèle local en dur AVANT l'appel ont été changés pour
#   passer `model=None` et laisser `resolve_model()` décider sur le PROMPT réel (transcript/
#   conversation/description inclus) plutôt qu'à l'aveugle — comportement identique à avant
#   si le cloud n'est pas configuré, amélioré sinon.
#
#   **Fraîcheur web** : rejeté la demande littérale (« chercher à chaque message ») —
#   ajouterait de la latence à toute question qui n'en a pas besoin (calcul, résumé de
#   fichier, action système). À la place : règle d'or #8 ajoutée au prompt système
#   (PRIORITAIRE, même famille que les 7 existantes) — ne jamais répondre "de mémoire" sur
#   une info possiblement périmée (version logicielle, actualité, prix, disponibilité,
#   événement récent) et appeler web_search/web_research AVANT de répondre dans ce cas.
#   Nouveau groupe de mots-clés dans `_KEYWORD_TOOLS` ("dernière version", "quoi de neuf",
#   "encore d'actualité", "vient de sortir", "à jour", "obsolète"...) qui inclut désormais
#   web_search/web_research dans la liste d'outils filtrée même sans mention explicite de
#   "web"/"internet" — sans ce mot-clé, ces formulations passaient à travers le filtrage
#   par mots-clés (le filtre sémantique aurait pu les rattraper, mais pas de façon fiable).
#
#   Testé en réel (curl direct contre le backend live, PAS de simulation) : `resolve_model()`
#   unit-testé (non-sensible → cloud, sensible → local, avec images → local, cloud désactivé
#   → local) ; requête "dernière version de Python actuellement disponible" → `web_search`
#   RÉELLEMENT appelé (DuckDuckGo, 8 résultats incluant Python 3.14.6, sources citées) sans
#   qu'aucun mot "web"/"internet" ne soit présent dans la question. `scripts/smoke_test_pages.py`
#   34/34 + `scripts/smoke_test_chat.py` 5/5 conversations, aucune régression.
#
# v2.123 (🧩 4 correctifs du système de Compétences) : demandé explicitement (« la partie
#   compétence peut être revue, améliorée, car dans l'état actuel ils ne sont pas très
#   fonctionnels ni opérationnels »). Avis donné AVANT implémentation (demandé explicitement,
#   audité via agent Explore plutôt que deviné) : l'hypothèse initiale de l'utilisateur
#   (un modèle cloud plus puissant générerait de meilleures compétences) ne correspondait
#   PAS aux données réelles — les 26 fichiers de compétences sont bien rédigés, les 36 noms
#   d'outils qu'elles référencent existent tous. Le vrai problème : 16/26 (62%) n'ont JAMAIS
#   été déclenchées une seule fois depuis leur création, et les 10 qui le sont affichent un
#   taux de succès suspicieusement parfait (100%, jamais mises à l'épreuve) — un problème
#   d'ACTIVATION, pas de génération. 4 bugs concrets trouvés et corrigés dans `skills.py`/
#   `agent.py` :
#   1. **Matching mono-message** (`agent.py::_match_skill`) : ne regardait QUE le dernier
#      message — un follow-up court ("vas-y", "ok fais-le") après une 1ère demande pertinente
#      ne portait jamais assez de signal pour re-déclencher la compétence. Corrigé : si le
#      message courant fait ≤4 mots, il est complété avec le tour utilisateur précédent
#      avant le matching (uniquement dans ce cas, pour ne pas diluer le matching des
#      demandes normales déjà auto-suffisantes).
#   2. **Repli embedding trop strict** (`skills.py::match()`) : si l'embedding échoue
#      (Ollama hors-ligne, timeout...), l'ancien calcul imposait un mur dur (overlap≥2 OU
#      trigger exact, sinon plafonné à 0.30 — toujours sous le seuil) qui désactivait
#      SILENCIEUSEMENT tout matching pour une requête n'ayant qu'UN mot-clé fort en commun.
#      Formule lissée (base 0.40/0.22/0 selon overlap au lieu d'un cliff binaire) + seuil
#      global 0.62→0.60 + cap lexical 0.30→0.35 (mots-clés déjà filtrés courts/vides par
#      `_keywords`, un recouvrement même partiel est un signal réel).
#   3. **Golden path corrompu** (`skills.py::record_success_trace`) : bug réel trouvé dans
#      les données de production — la compétence "migration-poste" avait mémorisé comme
#      "déroulé le plus efficace" 8 appels IDENTIQUES à `win_system_report` (une boucle
#      ratée mais réussie malgré tout), activement réinjectée comme exemple few-shot pour
#      REBOUCLER au prochain déclenchement. Dédoublonnage des appels consécutifs identiques
#      AVANT toute comparaison de longueur (le déroulé dédupliqué EST le vrai golden path).
#      Donnée corrompue existante nettoyée directement dans `data/skills_stats.json`
#      (8 appels → 1).
#   4. **`consolidate_obsolete_skills` ignorait les compétences jamais utilisées**
#      (`if not last_used: continue`) : aucune des 16 compétences jamais déclenchées n'était
#      donc JAMAIS révisée/archivée, quel que soit son âge — exemption permanente, aucune
#      boucle de rétroaction. Corrigé : pour une compétence sans `last_used`, la date de
#      dernière modification du fichier sert de référence d'âge (signal moins précis qu'un
#      usage réel, mais infiniment meilleur qu'une exemption à vie).
#   Testé en réel (pas de simulation) : `record_success_trace` unit-testé (8 appels
#   identiques → 1 stocké ; trace normale à 3 étapes → 3 stockés, inchangé) ; `match()`
#   testé sur les vraies compétences ("caractéristiques matérielles" → migration-poste,
#   "vas-y" seul → aucun match, comportement voulu) ; `consolidate_obsolete_skills()`
#   exécuté pour de vrai contre les données réelles (tous les fichiers ont <20 jours, donc
#   aucun archivage — confirmé sans erreur) ; requête chat live "mon imprimante ne répond
#   plus du tout" → la compétence `depannage-imprimante` (JAMAIS déclenchée avant ce
#   correctif) se déclenche désormais correctement. Smoke-tests 34/34 pages + 5/5
#   conversations, aucune régression.
#
# v2.124 (🧠 Compétences — recherche web + 3 améliorations + 5 nouvelles compétences) :
#   suite directe de v2.123, sur demande explicite (« regarde sur le web, github, forums
#   spécialisé AI... pour rendre cela plus puissant » + « pense à me faire de nouvelles
#   compétences liées à mon métier d'admin système/réseau et d'étudiant en recherche
#   informatique »). Recherche menée AVANT implémentation (Anthropic Agent Skills/SKILL.md
#   — le standard officiel du même type de système —, Voyager, littérature 2026 sur la
#   curation de bibliothèques de compétences SkillOS/SkillBrew). Bonne nouvelle validée par
#   la recherche : l'architecture de Marvin (traces de succès, auto-réparation, apprentissage
#   périodique) est déjà proche de l'état de l'art — pas de refonte nécessaire, 3 ajustements
#   ciblés :
#   A. **Descriptions plus explicites** : Anthropic documente que SES PROPRES modèles
#      sous-déclenchent une compétence si sa description n'énonce pas clairement LE
#      DÉCLENCHEUR — exactement cohérent avec la trouvaille v2.123 (62% jamais déclenchées).
#      Les 16 compétences dormantes ont eu leurs descriptions réécrites ("Se déclenche
#      pour...") + leurs listes de triggers étoffées avec des formulations naturelles
#      supplémentaires.
#   B. **Journal du dauphin** (`skills.py::_log_match_attempt`, nouveau fichier
#      `data/skills_match_log.jsonl`, endpoint `GET /api/skills/match_log`) : chaque
#      matching enregistre gagnant + 2ᵉ meilleur candidat + scores — donnée réelle pour juger
#      si un retrieval multi-compétences (façon Voyager, qui récupère le top-5 plutôt qu'un
#      seul gagnant) apporterait quelque chose, avant d'investir dans cette refonte plus
#      lourde. Diagnostique uniquement, aucune action automatique.
#   C. **Scan de chevauchement croisé** (`skills.py::find_overlapping_skills`, endpoint
#      `GET /api/skills/overlaps`) : compare TOUTES les compétences entre elles par
#      similarité d'embedding (pattern SkillOS/SkillBrew — curation à l'échelle de la
#      bibliothèque, pas seulement au sein d'une même compétence comme
#      `review_and_consolidate_learnings`). Exécuté pour de vrai sur les 31 compétences :
#      aucune paire au-dessus de 0.85 (pas de doublon problématique), les similarités
#      0.75-0.85 sont entre compétences légitimement voisines mais distinctes (onboarding/
#      offboarding, sauvegarde/restauration) — résultat rassurant, pas d'action requise.
#   **5 nouvelles compétences** ciblées métier (admin système/réseau + recherche
#   informatique), tous les outils référencés vérifiés existants avant écriture :
#   `audit-securite-reseau` (scan de ports/services/certificats TLS), `deploiement-multi-
#   serveurs` (commande sur plusieurs connexions SSH à la fois, `ssh_exec_multi`),
#   `veille-vulnerabilites-logiciels` (croise l'inventaire logiciel réel avec les CVE
#   récentes via web_search, s'appuie sur la règle de fraîcheur v2.122), `veille-recherche-
#   informatique` et `synthese-article-scientifique` (recherche/synthèse académique
#   structurée, distinct d'un résumé générique).
#   Testé en réel (curl contre le backend live, pas de simulation) : 31 compétences
#   chargées (26+5) confirmées via `/api/skills`. Scan de chevauchement exécuté pour de
#   vrai (résultats ci-dessus). Journal de matching vérifié avec 2 requêtes réelles :
#   "mon wifi se déconnecte tout le temps" → `depannage-wifi` gagne net (1.258 vs 0.805,
#   écart 0.453) ; "veille sur les dernières avancées en sécurité réseau" →
#   `veille-recherche-informatique` gagne (0.989 vs 0.916 pour veille-vulnerabilites-
#   logiciels, une confusion plausible et acceptable entre 2 compétences voisines).
#   Smoke-tests 34/34 pages + 5/5 conversations, aucune régression.
#
# v2.125 (🧠 "Marvin reste à réfléchir" — 3 correctifs) : signalé directement par
#   l'utilisateur (« je trouve souvent que Marvin continue de réfléchir sans rien faire et
#   je suis obligé d'arrêter »). Diagnostiqué sur les VRAIES conversations récentes
#   (agent Explore sur `secretary.db`, pas une supposition) : preuve d'un tour d'outil
#   silencieux de 3min10 sur une conversation réelle, plusieurs conversations coupées net
#   en plein tool_call sans suite (signature d'un arrêt manuel pendant le silence).
#   1. **Champ `thinking` d'Ollama jamais lu** : certains modèles (dont deepseek-v4-flash:
#      cloud, confirmé par un appel direct à l'API Ollama) renvoient leur raisonnement dans
#      un champ SÉPARÉ de `message.content`, avant la réponse/l'appel d'outil réel.
#      `agent.py` ne lisait que `content` → l'utilisateur ne voyait RIEN défiler pendant que
#      le modèle "pensait". `MessageBubble.jsx` avait DÉJÀ un bloc collapsible "🧠
#      Réflexion..." tout construit (parts de type 'reasoning') mais jamais alimenté —
#      branché maintenant (`ChatContext.jsx`, nouvel événement SSE `thinking`).
#   2. **Bug trouvé en corrigeant le point 1** : le handler `case 'text'` de `ChatContext.jsx`
#      reconstruisait `parts` en ne gardant que les tool-invocations, effaçant
#      silencieusement le bloc de réflexion dès le 1er token de réponse finale. Corrigé
#      (préserve aussi les parts 'reasoning') — vérifié en réel (Playwright) : le badge
#      "Réflexion..." apparaît PENDANT la frappe et survit après coup, contenu lisible.
#   3. **Résultats web énormes réinjectés à chaque tour** : une conversation réelle
#      cumulait jusqu'à 118 000 caractères de résultats `web_browse` (≈15 appels en rafale),
#      chacun restant dans l'historique pour tout le reste de la boucle — chaque appel
#      suivant au modèle cloud devenait plus lourd et plus lent. Plafond de
#      `execute_web_browse` abaissé (25000/60000 → 12000/20000 caractères).
#   **Découverte annexe pendant les tests, corrigée au passage** : deux questions anodines
#   ("combien font 47*53", "quelle est la capitale de la France") déclenchaient des
#   compétences totalement hors sujet (dépannage imprimante, pas-internet) à des scores
#   0.6-0.7 à peine au-dessus du seuil abaissé en v2.123 (0.60), quasi à égalité avec le
#   dauphin (écart 0.004 à 0.013) — du bruit de mesure, pas une vraie correspondance,
#   confirmé grâce au journal du dauphin construit en v2.124. Une compétence hors sujet
#   injectée dans le prompt peut faire dériver le modèle sur une question triviale —
#   contributeur plausible additionnel au ressenti "tourne en rond". Seuil relevé à 0.72 +
#   exige un écart minimum de 0.05 avec le dauphin, sinon aucun match plutôt qu'un match
#   ambigu (`skills.py::match`). Revérifié après coup que les VRAIS matches (score >0.95,
#   écart >0.07 observés en réel) passent toujours.
#   Testé en réel de bout en bout : SSE brut confirme le streaming `thinking` fonctionnel ;
#   Playwright confirme le rendu visuel (badge pendant la frappe + persistance après) sans
#   erreur console ; les 2 questions-pièges ne matchent plus aucune compétence
#   (`winner: null` au journal) tandis que `depannage-wifi` et `veille-recherche-
#   informatique` matchent toujours correctement. Smoke-tests 34/34 pages + 5/5
#   conversations.
#
# v2.126 (🇫🇷 réponse toujours en français + 🎯 pas de silence à MAX_TOOL_STEPS) : signalé
#   directement par l'utilisateur juste après la mise en prod de v2.125 (« je ne trouve pas ça
#   très pertinent et je voudrais que le résultat soit toujours en français »), en pointant sa
#   propre conversation en cours. Diagnostiqué sur cette VRAIE conversation (demande AD CS/Wazuh
#   à 08:36) plutôt que deviné : le modèle cloud actif (`deepseek-v4-flash:cloud`, routage
#   normal — requête non sensible) avait fait 3 `web_browse` puis appelé `ssh_list` (outil
#   totalement hors sujet) et conclu par une réponse finale ENTIÈREMENT EN ANGLAIS listant les
#   connexions SSH enregistrées — sans jamais répondre à la question posée (procédure de
#   certificat HTTPS AD CS→Wazuh). 2 causes réelles, pas une seule :
#   1. Le prompt système ne rendait le français qu'« par défaut », laissant la porte ouverte à
#      un basculement en anglais après avoir ingéré plusieurs pages sources anglaises (Wazuh
#      docs, notes.benheater.com). Durci en règle non négociable + 2 nouvelles règles d'or
#      (#9 : traduire systématiquement le contenu anglais des sources dans la réponse finale ;
#      #10 : rester sur la demande initiale, ne pas partir sur un outil annexe juste parce
#      qu'il est disponible/récent — explique directement l'appel `ssh_list` observé).
#   2. Bug structurel plus grave trouvé en reproduisant le cas en direct (requête de recherche
#      web forcée, curl SSE) : à l'atteinte de `MAX_TOOL_STEPS` (10), la boucle `agent.py`
#      terminait purement et simplement — AUCUN message sauvegardé, AUCUN texte streamé, juste
#      un `done` sec après le dernier `tool_end`. Reproduit avec 11 `tool_start` d'affilée et
#      zéro `text` en sortie — c'est le symptôme EXACT de « Marvin reste bloqué à réfléchir puis
#      s'arrête sans rien faire », indépendant du fix v2.125 sur le streaming `thinking` (qui
#      rend visible la RÉFLEXION mais ne garantissait pas une RÉPONSE). Corrigé : à l'atteinte
#      de la limite, un dernier appel Ollama SANS outils est forcé (nudge explicite « tu ne peux
#      plus utiliser d'outils, synthétise maintenant en français ») et son texte est streamé +
#      sauvegardé comme réponse finale, avec un repli textuel si même cet appel échoue.
#   Testé en réel de bout en bout (curl SSE, requête forcée à englober des sources anglaises) :
#   réponse finale intégralement en français, correctement traduite/synthétisée à partir de
#   docs anglaises (nginx.org), 7 appels d'outils sans dérive hors-sujet (vs. le `ssh_list`
#   observé avant fix). Smoke-test chat 5/5 après coup.
#
# v2.127 (🛡️ 2 règles d'or — sécurité dégradée par erreur + syntaxe non évaluée dans les docs) :
#   demandé par l'utilisateur (« que penses-tu de la dernière conversation ? corrige tout ce qui
#   ne va pas ») sur une VRAIE conversation (script d'installation GLPI sur Debian 13 + PDF
#   généré). Audit ligne par ligne du script produit par le modèle cloud actif, 3 défauts réels
#   trouvés :
#   1. L'étape « sécurisation de MariaDB » du script automatisé exécutait
#      `ALTER USER 'root'@'localhost' IDENTIFIED BY '';` — qui fait l'INVERSE de sécuriser :
#      sur Debian, root MariaDB utilise par défaut l'authentification unix_socket (pas de mot de
#      passe réseau) ; cette commande la REMPLACE par une authentification par mot de passe VIDE,
#      une régression de sécurité présentée comme un durcissement.
#   2. Le PDF généré contenait littéralement le texte `$(date '+%d/%m/%Y')` dans son pied de
#      page — une substitution shell jamais évaluée, écrite telle quelle par le modèle qui a
#      halluciné un contexte d'exécution shell pour du contenu Markdown statique.
#   3. La section « réinitialisation du mot de passe admin » du PDF fournissait un hash bcrypt
#      copié tel quel (probablement d'un tutoriel générique en ligne) en affirmant qu'il
#      correspond au mot de passe "admin" — invérifiable et une mauvaise pratique de toute façon
#      (un hash trouvé sur internet ne doit jamais être présenté comme fiable pour un reset admin).
#   Pas de bug logiciel Marvin ici (c'est un défaut de génération du LLM, pas du code) — 2
#   nouvelles règles d'or ajoutées au prompt système pour réduire la récidive sur cette CATÉGORIE
#   d'erreur : #11 (ne jamais dégrader une sécurité existante sous couvert de la « sécuriser »,
#   préférer la commande officielle interactive à une improvisation SQL/script) et #12 (jamais de
#   syntaxe shell/code non évaluée dans un document destiné à être lu tel quel ; jamais de
#   hash/identifiant trouvé en ligne présenté comme fiable pour un reset de credentials).
#
# v2.128 (📂 documents générés cliquables dans le chat) : demandé explicitement (« j'aimerais
#   pouvoir cliquer et ouvrir les documents générés directement depuis le chat »), sur la même
#   conversation GLPI que v2.127. Les outils de génération de document (`file_create_pdf`,
#   `document_generate`, `billing_quote_pdf`, `file_convert_docx_to_pdf`...) renvoient tous la
#   même forme `{success, message, path}` — jusqu'ici rendue par le fallback « succès générique »
#   de `MessageBubble.jsx` (un simple ✅ + message texte), obligeant à aller chercher le fichier
#   soi-même sur le disque. Nouveau composant `GeneratedFileCard` : détecte un résultat
#   `success + path` dont l'EXTENSION correspond à un type de document connu (pdf/docx/xlsx/
#   pptx/txt/md/csv...) — détection par extension plutôt que par nom d'outil un par un, pour
#   couvrir automatiquement tout futur outil de génération sans modification supplémentaire —
#   et affiche une carte cliquable (icône par type, nom de fichier, message de succès) qui
#   appelle `pc_open_file` (déjà utilisé par `FileExplorerCard.jsx` pour le même usage) au clic.
#   Testé en réel (Playwright + appel direct `pc_open_file` sur le chemin exact affiché) : la
#   carte s'affiche sans erreur console sur la conversation GLPI réelle, le clic déclenche bien
#   l'appel `/api/tools`, `pc_open_file` confirmé retourner `success:true` sur ce chemin.
#
# v2.129 (📐 règle d'or #13 — structuré + sécurisé + complet par défaut) : demandé explicitement
#   après l'audit du script GLPI v2.127 (« fait en sorte que ce que je demande à Marvin soit
#   toujours structuré et bien sécurisé et complet comme avec toi »). Les règles #7/#8/#11/#12
#   couvraient déjà des symptômes précis (hallucination d'identifiant, info périmée, régression
#   de sécurité déguisée, syntaxe non évaluée) mais rien n'énonçait le niveau de qualité ATTENDU
#   PAR DÉFAUT sur toute réponse technique — l'utilisateur veut ce standard systématique, pas
#   du cas par cas après coup. Nouvelle règle #13 (`agent.py`) qui consolide 3 exigences
#   explicites pour toute réponse de type script/procédure/config/installation : structure
#   (titres, étapes, tableaux — pas un mur de texte), sécurité (moindre privilège par défaut,
#   relecture mentale de chaque commande sensible avant écriture) et complétude (prérequis +
#   vérification finale, vérifier via web_search si un point technique récent est incertain
#   plutôt que de deviner). Renforce les règles existantes plutôt que de les dupliquer.
#
# v2.130 (🔒 règle #11 étendue — ne touche pas à un compte d'admin qui n'a rien demandé) :
#   demandé explicitement après vérification du fix v2.129 (« je veux pouvoir travailler avec
#   Marvin sans risque sur ses procédures/scripts/demandes techniques qui doivent être de niveau
#   professionnel »). Le test réel du fix v2.129 (script Nextcloud) avait montré une nette
#   amélioration mais un résidu : le script changeait toujours l'authentification root MariaDB
#   d'unix_socket (sûr par défaut sur Debian, local uniquement) vers un mot de passe — plus une
#   régression grave (mot de passe FORT généré, pas vide comme en v2.127) mais toujours une
#   modification non nécessaire d'un mécanisme qui n'avait rien demandé à être touché. Règle #11
#   étendue avec un principe plus large : si un compte/service a déjà une authentification sûre
#   par défaut, NE PAS LA MODIFIER même pour la "renforcer" — créer un compte applicatif DÉDIÉ
#   pour l'usage demandé (déjà la bonne pratique suivie pour la base de données elle-même) et
#   laisser le compte d'administration du service sous-jacent inchangé. Règle durcie une 2ᵉ fois
#   dans la foulée (interdiction explicite et nommée de `ALTER USER 'root'@'localhost'
#   IDENTIFIED BY` sur MariaDB/MySQL, sans exception) après un premier test resté positif.
#
# v2.131 (🛡️ filet de sécurité DÉTERMINISTE — le rappel textuel a un plafond d'efficacité) :
#   testé en réel (3 requêtes identiques « script d'installation Zabbix + MariaDB » contre le
#   modèle cloud actif APRÈS le durcissement v2.130 de la règle #11) — le script a QUAND MÊME
#   modifié le mot de passe root MariaDB dans 2 générations sur 3, malgré une interdiction
#   explicite et sans exception dans le prompt système. Conclusion actée avec l'utilisateur
#   (« je veux pouvoir travailler avec Marvin sans risque ») : un rappel textuel, même très
#   explicite, ne garantit JAMAIS un comportement 100% fiable sur un LLM probabiliste — durcir
#   encore le texte n'aurait fait que repousser le problème, pas le résoudre.
#   Ajout d'un filet DÉTERMINISTE (`agent.py::_scan_dangerous_script_patterns`), sur le même
#   principe que `security.py` mais pour du contenu généré plutôt que des commandes exécutées :
#   scan regex de la réponse finale (si elle contient un bloc de code) contre une liste de
#   motifs dangereux SANS AMBIGUÏTÉ (modification du mot de passe root MariaDB/MySQL, mot de
#   passe VIDE dans une commande d'authentification, `chmod -R 777`). Ne bloque ni ne modifie
#   RIEN (contrairement à `security.py` qui bloque des COMMANDES EXÉCUTÉES — ici c'est du texte
#   à LIRE) : ajoute un bandeau "⚠️ Vérification automatique de sécurité" visible et impossible
#   à manquer à la fin de la réponse, listant précisément ce qui a été détecté. Câblé aux 2
#   points de sortie de la boucle agent (réponse finale normale ET fin forcée à MAX_TOOL_STEPS,
#   v2.126). Best-effort : `_scan_dangerous_script_patterns` n'a jamais d'exception qui remonte.
#
# v2.132 (🌡️ température profil analysis abaissée 0.3→0.15) : question directe de l'utilisateur
#   (« peut-on changer la température via des commandes ollama pour le modèle cloud ? »).
#   Réponse : techniquement possible via `ollama create` + Modelfile, mais INUTILE pour Marvin —
#   vérifié dans le code que `agent.py` envoie déjà `system` et `options.temperature` explicitement
#   à CHAQUE appel `/api/chat`, quel que soit le modèle (local ou `:cloud`), ce qui prime toujours
#   sur un Modelfile figé côté Ollama. Proposé de baisser directement la température de Marvin à la
#   place — accepté (« oui, teste ça »).
#   `config.py::MODEL_PROFILES["analysis"]["temperature"]` 0.3→0.15 (même doctrine que le profil
#   `agent`, déjà à 0.1 — réponses techniques longues = tool-calling déterministe attendu aussi).
#   Testé en réel : 10 nouvelles générations (2 formulations différentes de script d'installation
#   touchant MariaDB) après la baisse → 1/10 a encore modifié le mot de passe root (vs ~2/3 avant
#   la baisse), et le filet déterministe v2.131 l'a correctement flaguée. Confirme que la
#   température seule ne suffit jamais à garantir 100% — c'est un complément au filet
#   déterministe, pas un remplacement.
#
# v2.133 (🛡️ filet déterministe étendu au CONTENU des documents générés) : suite de « continue
#   sur cette voie ». Angle mort trouvé en relisant le filet v2.131 : il ne scannait que la
#   réponse de CHAT visible, jamais les arguments passés aux outils de génération de document
#   (`file_create_pdf`, `document_generate`, `billing_quote_pdf`, `file_convert_docx_to_pdf`).
#   Or le PDF GLPI qui a motivé TOUT ce chantier (v2.127 — mot de passe root vidé, `$(date...)`
#   littéral) avait ses défauts dans le contenu du DOCUMENT, jamais dans le texte de chat
#   lui-même — le scanner v2.131 tel quel ne l'aurait donc PAS attrapé. Corrigé : scan de
#   `tool_args["content"]`/`["body"]` juste après l'exécution réussie d'un de ces 4 outils,
#   résultat stocké dans `result["security_warning"]` (nouveau champ), affiché dans
#   `GeneratedFileCard.jsx` sous la carte de fichier cliquable (bandeau rouge, toujours visible,
#   pas seulement dans le JSON brut).
#   Liste de motifs élargie au passage (`_DANGEROUS_SCRIPT_PATTERNS`) : `curl|sh`/`wget|sh`
#   (exécution de script distant sans inspection), `curl -k`/`--insecure` (TLS désactivé),
#   `PermitRootLogin yes`, désactivation de pare-feu (`ufw disable`/`iptables -F`), service
#   bindé sur `0.0.0.0`. + liste séparée `_DANGEROUS_DOCUMENT_PATTERNS` (substitution shell non
#   évaluée `$(date...)`) appliquée UNIQUEMENT au scan de document — ce motif est un FAUX POSITIF
#   garanti sur un scan de script ```bash générique (`$(hostname -I)` etc. y est parfaitement
#   normal), piège repéré et corrigé avant tout test.
#
# v2.134 (🩺 diagnostic PC réel + compétence dédiée + lisibilité chat) : demandé explicitement
#   sur une VRAIE conversation ("contrôle du pc pour connaître les problèmes logiciels et
#   physiques") — « fait tout et améliore la lisibilité de tout cela et fait en sorte que Marvin
#   crée les compétences au besoin ». Audit préalable : le rapport généré affirmait « aucune
#   alerte de surchauffe détectée » alors qu'AUCUN outil existant ne lit jamais de capteur de
#   température — une hallucination (règle #3) rendue possible par l'absence de la donnée
#   elle-même, pas par le modèle qui invente délibérément.
#   3 nouveaux outils, tous basés sur des données RÉELLES (jamais estimées) :
#   - `pc_hardware_temps` : capteur ACPI (CPU, souvent absent sur desktop — renvoie explicitement
#     "non disponible" plutôt que de deviner) + `nvidia-smi` (GPU, testé en réel : 49°C mesurés).
#   - `pc_disk_smart_health` : compteurs de fiabilité Windows Storage Management (usure SSD,
#     erreurs de lecture non corrigées) — plus profond que le simple `HealthStatus` déjà exposé
#     par `win_disk_info`. Testé en réel : fonctionne sans crash même quand les compteurs
#     reviennent `null` (courant selon le contrôleur disque — dépend du matériel, pas un bug).
#   - `pc_event_log_errors` : erreurs Système+Application des 7 derniers jours (Get-WinEvent,
#     un seul appel pour les 2 journaux, filtré Critique/Erreur) + détection de sources
#     récurrentes (signal de problème persistant vs ponctuel). Testé en réel : 20 événements
#     réels remontés ; timestamp corrigé pour être lisible humain (`.ToString(...)` dans le
#     script PS) au lieu du format .NET brut `/Date(...)/ ` initialement renvoyé.
#   Nouvelle compétence `data/skills/diagnostic-pc-complet.md` : bundle les 4 outils existants +
#   les 3 nouveaux + `web_search` pour une vérification RÉELLE des pilotes (au lieu du
#   « vérifie toi-même » précédent), avec consigne explicite anti-hallucination (ne jamais
#   affirmer une température/usure/erreur sans avoir appelé l'outil correspondant) et le format
#   de sortie de la règle d'or #13 (structuré/sécurisé/complet).
#   Lisibilité chat (`MessageBubble.jsx`) : 4 nouveaux rendus dédiés réutilisant `DashboardKit`
#   (déjà éprouvé sur Monitoring/Santé) — `win_system_report` en jauges CPU/RAM + barres disques
#   au lieu d'un JSON/tableau markdown brut, `pc_hardware_temps`/`pc_disk_smart_health`/
#   `pc_event_log_errors` en cartes/tableaux colorés (rouge sur seuil dépassé) au lieu du
#   fallback JSON générique.
#
# v2.135 (🔤 mojibake PowerShell corrigé — bug préexistant, pas une régression v2.134) :
#   l'utilisateur a signalé un souci pendant le test réel du diagnostic PC complet (« je pense
#   il y a un souci, coupe Marvin et relance-le proprement et fixe le souci »). Diagnostiqué
#   méthodiquement : chaque nouvel outil testé individuellement répond en 1-2s — pas de hang
#   réel, juste la lenteur normale d'un enchaînement de ~8 appels d'outils+LLM. MAIS un vrai
#   bug trouvé au passage sur `execute_pc_event_log_errors` : les accents français ("s'est",
#   "réseau") ressortaient en mojibake ("s�est", "r�seau"). Vérifié que `win_event_log`
#   (existant, non touché par v2.134) a EXACTEMENT le même défaut — donc préexistant, pas
#   introduit par les nouveaux outils.
#   Cause racine : `execute_pc_run_powershell` capture la sortie avec `text=True,
#   encoding="utf-8", errors="replace"` — malgré le `[Console]::OutputEncoding=UTF8` injecté en
#   tête de script, PowerShell en mode `-EncodedCommand` + stdout redirigé écrit en pratique en
#   Windows-1252 (confirmé : l'apostrophe typographique Windows, octet 0x92 en cp1252, est un
#   octet UTF-8 invalide isolé → remplacé silencieusement par `errors="replace"`). Corrigé :
#   capture des octets bruts (`text=False`), décodage UTF-8 strict en priorité, repli sur cp1252
#   UNIQUEMENT si le décodage UTF-8 échoue réellement — bénéficie à TOUS les outils qui passent
#   par `execute_pc_run_powershell` (win_event_log, win_disk_info, pc_disk_smart_health,
#   pc_event_log_errors, etc.), pas seulement aux 3 nouveaux.
#
# v2.136 (⏱️ diagnostic PC complet — pas de bug, mais 9,4 min de latence expliquée + resserrée) :
#   après le fix v2.135, le frontend était aussi tombé (port 3000 injoignable — relancé
#   proprement sur demande explicite, aucun lien avec le code : `npm run dev` a démarré sans
#   erreur, donc pas une régression de `MessageBubble.jsx`). Rejoué le diagnostic complet
#   réel de bout en bout (SSE brut, 563s) pour vérifier : la RÉPONSE FINALE est excellente
#   (données réelles : GPU 49°C, SMART sain, 8 erreurs DNS récurrentes détectées, service en
#   échec identifié, 26 programmes au démarrage listés) — aucun bug de correction, juste une
#   lenteur réelle. Cause : 11 appels d'outils séquentiels au lieu des 7 prévus par la
#   compétence (le modèle a aussi appelé `win_network_config`, `win_startup_programs`,
#   `pc_process_list`, `file_large_finder`, non listés) — chaque aller-retour vers le modèle
#   cloud coûtant ~30-60s indépendamment du volume de sortie (latence API, pas de génération).
#   `data/skills/diagnostic-pc-complet.md` resserrée : consigne explicite de ne PAS appeler
#   d'outils hors de la liste des 7 sans mention explicite de l'utilisateur — la liste `tools:`
#   du frontmatter est ADDITIVE (ajoute au catalogue déjà filtré par mots-clés) et non
#   restrictive (vérifié dans `agent.py::run_agent`), donc seule une consigne dans le corps de
#   la compétence peut influencer ce comportement (pas de garantie à 100%, même limite
#   structurelle que documentée en v2.130/131 sur les LLM probabilistes).
#
# v2.137 (🔧 3 nouveaux outils + correctif retry Ollama) : sur demande explicite (« fait les 3
#   et corrige skills/suggest »), suite à l'audit v2.136 (905 exécutions réelles analysées :
#   43/43 outils OK sur l'échantillon système, aucun échec récent significatif ; `calendar_list`
#   avait un pic de 60 échecs historiques mais auto-résolu depuis 3 semaines).
#   BUG RACINE trouvé en diagnostiquant la lenteur de `/api/skills/suggest` (timeout dépassé à
#   5 min, backend resté sain) : `tools.py::_ollama_generate` retentait le modèle PRIMAIRE 3×
#   AU TIMEOUT COMPLET avant même d'essayer le repli léger — pire cas 3×240s = 12 min rien que
#   sur le primaire, pour un point d'entrée partagé par 13+ outils. Un timeout sur un GROS
#   prompt (comme les ~120 messages analysés par suggest_skills) est structurel, pas un blip
#   réseau transitoire — réessayer à l'identique échoue pareil. Corrigé : 1 essai primaire au
#   timeout complet, 1 SEUL retry primaire si l'échec n'était PAS un timeout (connexion/5xx
#   ponctuel — là un retry a du sens), puis repli léger à timeout RÉDUIT (30-60s). Pire cas
#   ramené de 4×timeout à timeout+timeout_léger — pour `/api/skills/suggest` (timeout=240),
#   ~240s+60s=300s max au lieu de jusqu'à 960s+.
#   3 nouveaux outils (`pc_hardware_temps`/`pc_disk_smart_health`/`pc_event_log_errors` déjà
#   en v2.134) : `win_firewall_status` (profils pare-feu réels + nb règles entrantes autorisées,
#   rendu structuré au lieu de parser du texte PowerShell brut) ; `pc_driver_check` (recherche
#   web CIBLÉE et systématique pour un composant donné — remplace le pari que le modèle pense
#   à appeler `web_search` avec une bonne requête, la compétence diagnostic-pc-complet l'utilise
#   désormais explicitement) ; repli OAuth pour `calendar_list` quand le compte de service
#   renvoie 404 (l'agenda personnel n'a pas été partagé avec l'e-mail du compte de service) —
#   directement motivé par les 60 échecs historiques trouvés dans l'audit, même s'ils sont
#   actuellement dormants.
#
# v2.138 (🧱 4 piliers de fiabilité — validation, tendance, dashboard, fiabilité composée) : sur
#   demande explicite (« fait le tout les points »), suite à une recherche web sur le tool-calling
#   agentique et le monitoring IT 2026.
#   1. **Validation des arguments AVANT exécution** (`agent.py::_validate_tool_args`) : couche
#      manquante des 3 recommandées (validation → retry ciblé → decoding contraint — la 2ᵉ existe
#      déjà via le garde de sécurité + le repli léger v2.137). Conservatrice à dessein : vérifie
#      seulement la PRÉSENCE des paramètres obligatoires déclarés dans TOOLS_SPEC, pas de
#      coercition de type stricte qui casserait des appels qui marchent déjà.
#   2. **Suivi de tendance** (`system_snapshots` + `pc_health_trend` + `_health_trend_worker`) :
#      un instantané quotidien (RAM/disque/usure SSD/erreurs récurrentes, via psutil + les outils
#      v2.134) plutôt qu'un instantané isolé — permet de répondre « le disque sera plein dans
#      combien de temps ? » avec une vraie extrapolation au lieu d'un pourcentage figé.
#   3. **Tableau de bord de fiabilité des outils** (`db.get_tool_reliability` + `/api/history/
#      reliability` + outil `pc_tool_reliability`) : les données existaient déjà dans
#      `tool_executions` mais n'étaient jamais agrégées par TAUX D'ÉCHEC, seulement par volume —
#      exactement ce qui a permis de rater 60 échecs de `calendar_list` jusqu'à une requête SQL
#      manuelle. Ferme cette boucle : c'est maintenant une donnée consultable, pas un audit ad hoc.
#   4. **Compensation de la fiabilité composée** : à 95% de fiabilité par appel, une chaîne de 8
#      outils ne réussit globalement qu'à ~66% (source : littérature 2026 sur les agents LLM).
#      Trace désormais dans `audit.jsonl` (`_long_tool_chain`) dès qu'un tour dépasse 8 appels —
#      visibilité pure, aucun changement de comportement, pour repérer ce signal sans recompter
#      à la main comme fait pour le diagnostic v2.136.
#
# v2.139 (📡 traçabilité par conversation + inventaire réseau + connecteurs ITSM multi-produit) :
#   sur demande explicite (« fait tout à ceci près que les connecteurs doivent couvrir une large
#   gamme de produits qui me seront utiles »), suite à une recherche web sur l'observabilité des
#   agents IA et les outils d'inventaire IT 2026.
#   BUG TROUVÉ EN IMPLÉMENTANT (pas cherché délibérément) : la boucle de chat (`agent.py`)
#   n'écrivait JAMAIS dans `tool_executions` — seuls `/api/tools` (boutons UI), cron, ssh_exec
#   REST et email_send y écrivaient. Le tableau de bord de fiabilité v2.138 ne voyait donc
#   qu'une fraction du vrai usage (les appels PILOTÉS PAR LE LLM, la majorité en pratique,
#   étaient invisibles). Corrigé : `db.log_execution` appelé depuis la boucle de chat avec
#   timing réel + `conversation_id` pour corrélation.
#   1. **Traçabilité par conversation** : colonne `conversation_id` sur `tool_executions` +
#      `db.get_conversation_trace` + outil `pc_conversation_trace` — chronologie complète d'un
#      tour (durée de chaque outil, ordre réel), remplace le recomptage manuel des `tool_start`
#      fait plusieurs fois cette session pour diagnostiquer une lenteur.
#   2. **Inventaire réseau persistant** (mini-CMDB) : table `network_devices` + `net_inventory_
#      scan` (scan + enregistrement, première/dernière apparition) + `net_inventory_list` +
#      `net_inventory_annotate` (nom personnalisé/notes) — un scan devient un inventaire
#      consultable dans le temps, pas un instantané jetable.
#   3. **Connecteurs ITSM multi-produit** : architecture GÉNÉRIQUE (`itsm_ticket_list`/
#      `itsm_ticket_create`/`itsm_asset_list`, paramètre `system`) — ajouter un nouveau produit
#      (Zammad, osTicket, Freshservice...) ne touche que `_ITSM_BACKENDS`, jamais les outils.
#      GLPI implémenté en premier (en cours de déploiement réel par l'utilisateur) via son API
#      REST (`initSession`/`killSession` par appel, credentials via `credentials_manager`).
#      `itsm_ticket_create` ajouté à `DANGEROUS_TOOLS` (confirmation obligatoire — visible par
#      d'autres personnes dans le système externe).
#
# v2.140 (📎 glisser-déposer + pièces jointes multiples dans le chat) :
#   sur demande explicite (« fait le glisser-déposer et les pièces jointes multiples »),
#   2 des 3 items frontend laissés de côté en v2.139 (le 3e, templates de prompt, non demandé
#   ici). Changement 100% frontend (`components/chat/ChatInput.jsx`), aucune logique Python
#   modifiée — HMR Next.js suffit, pas de redémarrage backend nécessaire.
#   - `attachedFile` (objet unique) → `attachedFiles` (tableau) : `uploadDocFile(file)` extrait
#     la logique d'upload en helper réutilisable, `handleDocSelect` traite plusieurs fichiers
#     en parallèle (`Promise.all`), chaque fichier a sa propre carte avec bouton de retrait
#     individuel (`removeAttachedFile(idx)`). `doSubmit` combine tous les documents lisibles
#     en un seul message avec un bloc "📎 Document joint « nom » :" par fichier.
#   - Glisser-déposer : handlers `onDragEnter/Leave/Over/Drop` sur le `<form>`, compteur
#     `dragCounter` (ref) pour gérer correctement les événements imbriqués des enfants (sinon
#     l'overlay clignote), classification par `file.type.startsWith('image/')` pour router vers
#     le bon pipeline existant (upload image vs upload document). Overlay visuel (bordure
#     pointillée accent, message) affiché pendant le survol.
#   Vérifié en réel (Playwright, channel="chrome") : 0 erreur console au chargement ; 2 fichiers
#   .txt réels attachés via l'input caché → 2 cartes distinctes avec comptage de caractères
#   exact (35/36) ; `dragenter` synthétique → overlay rendu correctement ; `drop` synthétique
#   avec fichier réel → traité et affiché (35 car.) ; test de bout en bout (2 fichiers + question
#   + soumission) → message combiné correct avec les 2 documents étiquetés séparément, Marvin
#   traite normalement derrière. `scripts/smoke_test_chat.py` : 5/5.
#
# v2.141 (☁️ routage cloud par TÂCHE + 🧠 passe de critique 2e modèle) :
#   sur demande explicite (« je préfère que l'on travail le plus possible avec les
#   models cloud [...] fait aussi la critique [...] revue critique d'un autre llm
#   avant d'envoyer la réponse »), suite à une recherche web sur les benchmarks
#   agentiques 2026 des modèles cloud Ollama disponibles.
#   VÉRIFIÉ EN DIRECT avant implémentation : `cloud_overrides` était déjà appliqué
#   aux 3 profils (agent/chat/analysis), donc tout ce qui n'est pas sensible passait
#   déjà par le cloud — la préférence de l'utilisateur était déjà largement respectée.
#   Le vrai écart : un SEUL modèle cloud (deepseek-v4-flash) pour tout, alors que les
#   benchmarks montrent des écarts nets par spécialité (GLM-5.2 : 90,6% tool-calling,
#   meilleur du comparatif ; qwen3-coder:480b : nettement meilleur en code long).
#   1. **Routage par TÂCHE** (`cloud_routing.py::detect_task/get_task_overrides`) :
#      un signal détecté dans le message (script/installation/commande/docker...)
#      route vers `cloud_task_overrides["code"]` (qwen3-coder:480b-cloud), prioritaire
#      sur l'override de PROFIL — câblé à la fois dans `agent.py::run_agent` (boucle
#      principale) et `cloud_routing.py::resolve_model()` (appels LLM internes aux
#      outils), mêmes garanties (cloud_enabled + non-sensible) jamais contournées.
#      Réglage appliqué : agent→glm-5.2:cloud (le généraliste agentique était sur le
#      modèle le MOINS bon des 3 en tool-calling), chat/analysis→deepseek-v4-flash.
#   BUG TROUVÉ EN IMPLÉMENTANT (pas cherché délibérément) : `is_cloud_model()` ne
#      testait que le suffixe `:cloud` — or `qwen3-coder:480b-cloud` (et plusieurs
#      autres modèles cloud installés) suffixent le TAG par `-cloud`, pas `:cloud`.
#      La protection mid-boucle (bascule vers le local si un outil sensible est
#      appelé en cours de tour) ne les aurait JAMAIS reconnus comme "cloud" — fuite
#      potentielle silencieuse. Corrigé (accepte les deux suffixes).
#   2. **Passe de critique par un 2e modèle** (`agent.py::_run_critique_pass`) :
#      après le scanner déterministe existant (v2.131/2.133, motifs regex connus
#      à l'avance), un vrai jugement de modèle — principe Mixture-of-Agents (un 2e
#      regard indépendant détecte ce qu'un modèle ne voit pas dans sa propre sortie).
#      Scope VOLONTAIREMENT restreint aux réponses contenant un bloc de code (même
#      critère que le scanner) : appliquer ça à chaque message aurait doublé la
#      latence pour zéro bénéfice (régression déjà vécue et corrigée v2.125/2.126).
#      Produit un BANDEAU visible, jamais une réécriture silencieuse (invérifiable).
#      Modèle critique DIFFÉRENT du modèle qui a répondu (diversité de jugement),
#      reste dans les modèles cloud déjà configurés par l'utilisateur ; repasse en
#      local si la requête est sensible (mêmes garanties que le reste du module).
#   ITÉRATION SUR LE PROMPT (testé, pas supposé) : 1er prompt trouvé TROP sensible
#      (flaguait "usage de sudo" et "vérification finale manquante" sur une réponse
#      déjà propre — faux positif reproduit en test direct) → resserré à 4 catégories
#      GRAVES uniquement (ID inventé, info fausse, régression sécurité, syntaxe non
#      évaluée), avec consigne explicite d'ignorer le style. Re-testé : le cas propre
#      ne déclenche plus, le cas dangereux (mot de passe root vidé) déclenche toujours.
#      2e bug trouvé en testant : un appel a dégénéré en sortie quasi vide ("-" seul)
#      → filet de longueur minimale ajouté (sinon bandeau vide affiché pour rien).
#   Testé en réel (curl SSE + appels directs à `_run_critique_pass`) : "quelle heure
#   est-il" → glm-5.2:cloud ; "script bash installation nginx" → qwen3-coder:480b-cloud
#   (routage tâche confirmé) ; requête avec "mot de passe" → reste local qwen2.5:14b
#   (garde de sensibilité intacte) ; critique testée 3× sur réponse dangereuse (mot de
#   passe root vidé) → détectée à chaque fois ; testée 2× sur réponse propre (install
#   nginx) → aucun faux positif après resserrage du prompt.
#
# v2.142 (🚀 « surpasser le payant » — 4 fonctionnalités + 1 BUG RACINE majeur trouvé
#   en cours de route) : sur demande explicite (« continue de faire en sorte que le
#   chat devienne meilleur que les modèles payants [...] propose-moi des améliorations
#   de fonctionnalité et d'intelligence » puis « fait tout »), suite à une recherche
#   web sur les fonctionnalités phares 2026 de ChatGPT/Claude/Gemini/Perplexity,
#   croisée avec un audit du code existant (pas juste supposé).
#
#   1. **Sécurité `code_python` + vrai Code Interpreter** : l'ancien `execute_code_python`
#      tournait par `exec()` DANS le process du backend, avec `os` importé SANS
#      CONDITION et une liste noire par SOUS-CHAÎNE littérale — contournable
#      (`getattr(os,'sys'+'tem')(...)` ne contient aucune chaîne interdite). Réécrit :
#      exécution dans un SOUS-PROCESSUS isolé (`.venv` python, cwd dédié), analyse AST
#      STRUCTURELLE avant exécution (`_scan_code_ast` — détecte tout `import`/`eval`/
#      `exec`/`open` quelle que soit l'obfuscation, puisque sans l'import le nom
#      n'existe simplement pas). Bonus : tout fichier écrit (graphique matplotlib, CSV)
#      est automatiquement détecté et affiché cliquable dans le chat (réutilise
#      GeneratedFileCard v2.128, étendu aux images avec vignette inline + tableau de
#      fichiers multiples).
#   2. **`web_deep_research`** : recherche multi-passes (recherche → juge les trous →
#      recherche complémentaire ciblée, jusqu'à 6 fois) avec rapport structuré à
#      citations numérotées — équivalent Deep Research de tous les concurrents payants.
#      Outil séparé de `web_research` (déclenché uniquement sur demande explicite,
#      plusieurs minutes d'exécution).
#   3. **Projects avec instructions persistantes** : un projet n'était jusqu'ici qu'un
#      NOM. Colonne `instructions` ajoutée, injectée automatiquement dans le prompt
#      système de toute conversation du projet (`PUT /api/projects/{id}`, panneau ⚙️
#      dans la sidebar) — équivalent Claude/ChatGPT Projects.
#   4. **`ai_model_council`** : interroge plusieurs modèles cloud DIFFÉRENTS en
#      parallèle sur la même question et synthétise accord/désaccord — équivalent
#      Model Council de Perplexity (fév. 2026). Marvin a plus de diversité de modèles
#      (7 cloud installés) que le conseil à 3 de Perplexity. Explicite, jamais par défaut.
#
#   🔴 BUG RACINE TROUVÉ EN DIAGNOSTIQUANT LE POINT 3 (pas cherché délibérément) : les
#      instructions de projet n'avaient AUCUN effet malgré une injection confirmée
#      correcte dans `system_prompt`. Isolé par test direct contre Ollama : le champ
#      TOP-LEVEL `"system"` de `/api/chat` est SILENCIEUSEMENT IGNORÉ — reproduit 0/3
#      sur glm-5.2, deepseek-v4-flash ET qwen2.5:14b LOCAL (donc pas spécifique à un
#      modèle ni au cloud), avec et sans `tools` (donc pas spécifique au tool-calling).
#      Le MÊME contenu placé comme message `{"role":"system", ...}` en tête de
#      `messages[]` fonctionne 3/3. Corrigé aux 2 points d'appel Ollama dans
#      `agent.py::run_agent` (champ `system` gardé en redondance défensive, ne coûte
#      rien). IMPACT : ce bug affectait potentiellement TOUTES les règles d'or de
#      `_build_system_prompt` depuis leur introduction (français forcé, anti-
#      hallucination, sécurité #7-13...) — explique en partie le "plafond de fiabilité
#      du prompt engineering" observé et documenté à plusieurs reprises cette session
#      (v2.125-2.133). Un commentaire de code déjà présent (v2.123, mémoire/recall
#      injecté dans le dernier message utilisateur "sinon noyée dans le long prompt
#      système et ignorée par le modèle") avait déjà touché du doigt le symptôme sans
#      identifier la cause exacte (attribué à la dilution, pas à un champ ignoré).
#   Testé en réel : régression vérifiée après le fix (règle française toujours
#   respectée sur question anglaise, tool-calling toujours fonctionnel 2/2 outils
#   appelés) + `scripts/smoke_test_chat.py` 5/5 ; instructions de projet confirmées
#   appliquées de bout en bout via vrai chat (tag exact retrouvé dans la réponse) ;
#   `code_python` : import os/eval/exec/__import__ tous bloqués sans confirmation,
#   code propre exécuté directement, graphique matplotlib capturé et chemin renvoyé ;
#   `web_deep_research` : rapport réel généré (4 sources, 1 passe) ; `ai_model_council` :
#   2 modèles consultés en parallèle, synthèse cohérente produite.
#
# v2.143 (🧠 RAG agentique pour document_ask) : sur demande explicite (« continue sur
#   cette voie pour augmenter le niveau d'intelligence de Marvin »), suite du chantier
#   v2.142. `document_ask` faisait une recherche UNIQUE et figée (naive RAG) — même
#   limite que celle corrigée pour `web_research`→`web_deep_research` en v2.142, jamais
#   appliquée au RAG documentaire local. Ajouté : après la 1ʳᵉ recherche, un petit
#   modèle JUGE si le contexte récupéré suffit ; sinon reformule UNE requête
#   complémentaire (mots-clés différents) pour une 2ᵉ recherche, résultats fusionnés
#   (dédoublonnés par texte) avant la synthèse finale. Coût borné à AU PLUS 1 recherche
#   + 1 petit appel de jugement supplémentaires (pas une boucle non bornée comme
#   `web_deep_research` — le corpus local est petit, pas besoin de 6 passes).
#   Recherche menée avant implémentation : vérifié que le paramètre Ollama `think`
#   n'apporte AUCUNE différence sur les modèles cloud installés (glm-5.2 émet déjà
#   son raisonnement par défaut, avec ou sans le flag — testé en isolation, résultat
#   identique) — piste explorée puis écartée sur preuve, pas laissée en l'état.
#   Testé en réel : indexation d'un document de test à 2 sections de vocabulaire
#   disjoint (installation technique / code de facturation), question portant sur les
#   deux → réponse complète et correcte, citée, avec fusion de plusieurs passes de
#   recherche confirmée (champ `sources` enrichi) ; document de test retiré de l'index
#   après coup. `scripts/smoke_test_chat.py` 5/5 après coup (aucune régression).
#
# v2.144 (🔐 SSH ad hoc + garde-fou "écrire ≠ exécuter" + règle d'or #14) : audit d'une
#   vraie conversation demandé explicitement (« regarde les dernières conversations et
#   dis-moi ce que tu penses de ce comportement »). Trouvé (pas supposé) : sur « script
#   d'installation de zabbix server sur debian 13 avec mariadb », l'agent avait appelé
#   `pc_run_command` avec un script RHEL/CentOS (dnf, systemctl) SUR LA MACHINE WINDOWS
#   LOCALE — sans dégât (dnf n'existe pas sous Windows) mais révélateur d'une confusion
#   « écrire une commande » / « l'exécuter ICI ». `pc_run_command` n'est routé par aucun
#   mot-clé (arrive via similarité sémantique, correctement) — le vrai trou : aucune des
#   13 règles d'or n'interdisait explicitement cette confusion.
#   1. **Règle d'or #14** : ne jamais confondre écrire un script pour un AUTRE système
#      (OS différent, machine distante) avec l'exécuter localement. N'exécute sur LA
#      machine locale que si explicitement demandé pour elle ; pour une machine
#      distante, utilise `ssh_exec`/`ssh_write_and_run` — jamais `pc_run_command` comme
#      substitut. Testé en réel : reproduction EXACTE du message qui a causé le bug
#      d'origine → 0 appel d'outil cette fois, script livré directement en texte avec
#      une note explicite sur la machine cible.
#   2. **Filet déterministe complémentaire** (`security.py::detect_cross_platform_
#      mismatch`) : avant toute confirmation de `pc_run_command`/`pc_run_powershell`,
#      détecte des motifs clairement non-Windows (sudo, apt/dnf/yum, systemctl, chmod
#      +x, shebang bash...) et enrichit le message de confirmation d'un avertissement
#      visible — pas un blocage dur (une commande Linux n'est pas catastrophique en
#      soi, WSL/tests de syntaxe sont légitimes), mais l'HUMAIN voit l'alerte avant de
#      cliquer confirmer, même si le jugement du modèle a échoué malgré la règle #14.
#      Bug trouvé au passage : `ssh_exec_multi` n'avait JAMAIS le garde `security.
#      guard_result()` (présent sur `ssh_exec` depuis v2.117) — corrigé, d'autant plus
#      important qu'elle vise plusieurs machines à la fois.
#   3. **SSH ad hoc** (`_resolve_ssh_target`, partagé par `ssh_exec` et le nouvel outil
#      `ssh_write_and_run`) : demandé explicitement (« si je lui demande de se connecter
#      avec cet ip et ces credentials il doit pouvoir le faire »). `ssh_exec` accepte
#      maintenant host/username/password/private_key DIRECTEMENT, sans connexion
#      sauvegardée au préalable — même garde-fou déterministe, même confirmation
#      obligatoire, rien d'affaibli. Connexion ad hoc réussie → `suggest_save_
#      connection` proposé (jamais automatique, l'utilisateur décide).
#   4. **`ssh_write_and_run`** (nouvel outil) : écrit un script généré sur une machine
#      distante via SFTP PUIS l'exécute — pour « crée un script d'installation de X et
#      lance-le sur ce serveur » en un seul geste, sans heredoc bash fragile dans
#      `ssh_exec`. Contenu passé par le même `security.guard_result()`.
#   Testé en réel : `detect_cross_platform_mismatch` 5/5 commandes Linux détectées, 3/3
#   commandes Windows silencieuses ; `ssh_exec`/`ssh_write_and_run` ad hoc — validation
#   des paramètres manquants, contenu catastrophique bloqué par le garde déterministe
#   AVANT toute tentative SFTP, connexion vers une IP injoignable tentée pour de vrai
#   et échoue proprement (timeout, pas un crash) ; reproduction du bug d'origine → 0
#   appel d'outil, script direct. `scripts/smoke_test_chat.py` 5/5.
#
# v2.145 (🚀 3 idées de GPT-5.6 Sol/ChatGPT Work — Sites, Ultra mode, tâche longue) : sur
#   demande explicite (« regarde les nouveautés [ChatGPT Sol/GPT-5.6] et dis-moi ce qu'on
#   peut reprendre » puis « les 3 »), recherche web menée avant implémentation.
#
#   1. **`webapp_create`** (« ChatGPT Sites ») : génère une mini-appli web autonome (HTML/
#      CSS/JS self-contained) ouverte dans le navigateur par défaut — réutilise `pc_open_
#      file`/`os.startfile()` tel quel (déjà le bon comportement pour un .html, zéro code
#      supplémentaire) et `GeneratedFileCard` (v2.128) étendu aux .html/.htm.
#   2. **`ai_subagents_run`** (« Ultra mode ») : décompose un objectif en 2-5 sous-tâches
#      INDÉPENDANTES traitées en parallèle (raisonnement, pas d'accès outils) puis
#      synthétisées — positionnement HONNÊTE dans la description : PAS de vrais sous-agents
#      avec outils comme Ultra (coordination "dans les poids" du modèle), un vrai gain de
#      rapidité/qualité sur des tâches qui se décomposent en angles indépendants.
#   3. **Tâche longue autonome** (« ChatGPT Work », allégé) : `long_task_start` décompose
#      un objectif en checklist (table `tasks` existante), avance immédiatement dans le
#      tour courant, puis programme un job CRON (`_long_task_resume`, nouveau cas spécial
#      dans `_cron_worker`) qui relance un VRAI tour `run_agent` (outils complets) toutes
#      les 5 min jusqu'à ce que tout soit fait. `long_task_status`/`long_task_stop` pour le
#      contrôle utilisateur. Positionnement honnête : reprise toutes les 5 min, pas un
#      process continu pendant des heures (infra cloud dédiée chez OpenAI).
#      **3 bugs trouvés en testant EN RÉEL** (pas supposés) :
#      a) Nommer littéralement les outils dans le message de reprise ("Utilise long_task_
#         status... task_update...") déclenchait la règle d'or #6 (outil explicite cité =
#         SEUL outil autorisé), bloquant l'accès aux VRAIS outils nécessaires pour avancer
#         — corrigé en décrivant l'étape en PROSE sans jamais nommer un outil précis.
#      b) `long_task_status` n'exposait pas l'`id` réel de la tâche → le modèle inventait
#         un identifiant (le tag, un numéro de position) pour `task_update`, échec
#         systématique — corrigé en donnant l'ID exact de la PROCHAINE étape directement
#         dans le message de reprise.
#      c) Une reprise SANS limite de temps peut enchaîner assez d'appels d'outils/cloud
#         pour prendre plusieurs MINUTES (même symptôme déjà documenté en v2.136) —
#         `asyncio.wait_for` borne chaque reprise à 3 min (buffer avant le prochain cycle
#         à 5 min) ; la progression déjà faite reste sauvegardée (run_agent écrit chaque
#         message au fil de l'eau), seule la suite est coupée et reprise au cycle suivant.
#      Petit correctif de qualité au passage : le prompt de décomposition demandait des
#      "étapes actionnables" sans préciser PAR QUI — le modèle proposait parfois des
#      instructions manuelles ("appuyez sur la touche Windows") inexécutables par un
#      agent autonome — précisé explicitement dans le prompt.
#   Testé en réel de bout en bout (2 fois, avec fix) : conversation réelle créée, tâche
#   longue démarrée, checklist créée avec IDs réels, job cron déclenché par le VRAI worker
#   (pas simulé), reprise complétée dans le délai borné, backend resté réactif tout du
#   long (vérifié par sondage pendant l'exécution) ; décomposition re-testée après le
#   correctif de prompt → étapes orientées outils au lieu d'instructions manuelles.
#   `ai_subagents_run` testé en réel (3 sous-tâches sécurité réseau, réponses détaillées
#   et correctes, synthèse cohérente) ; `webapp_create` testé (fichier HTML généré et
#   correctement enveloppé). `scripts/smoke_test_chat.py` 5/5, tous les artefacts de test
#   nettoyés (cron/tâches/conversations).
#
# v2.146 (🎯 UI — bandeau de MODE + langage clair + repli d'étapes + tâche de fond visible) :
#   sur demande explicite (« retravaille l'UI du chat pour que l'on sache que Marvin selon
#   nos requêtes travaille d'une certaine manière précise »), recherche menée sur les
#   patterns 2026 (Perplexity Pro Search : étapes en langage clair, repliées par défaut,
#   réponse prioritaire). Changement 100% frontend, aucune logique Python modifiée.
#   1. **Bandeau de mode** (`MessageBubble.jsx::TurnModeBadge`) : pilule colorée en tête de
#      réponse dès qu'un outil est appelé — 🔍 Recherche approfondie, 🧑‍🤝‍🧑 Panel d'experts IA
#      (nom choisi après retour explicite — « conseil de modèles » jugé pas assez parlant),
#      🧩 Sous-tâches parallèles, 🗂️ Tâche longue démarrée, 🐍 Code Interpreter, 🌐 Mini-appli
#      web, 🧠 Compétence activée, ou 🛠️ Agent (outils) en repli générique. Détecté par le
#      nom d'outil appelé dans le tour — aucun événement SSE supplémentaire nécessaire.
#   2. **Noms d'outils en langage clair** : le dictionnaire `toolLabels` existant (v2.9x)
#      était incomplet — tous les outils v2.130-2.145 (ssh_*, code_python, document_*,
#      long_task_*, ai_*...) retombaient sur leur nom technique brut. Étendu + repli
#      "snake_case → Mots séparés" pour tout outil non listé plutôt que d'exposer le nom
#      interne tel quel.
#   3. **Repli des étapes** : au-delà de 3 appels d'outils dans un tour, les cartes se
#      replient par défaut derrière "✅ N/M étape(s) effectuées ▼ Afficher" — la réponse
#      reste prioritaire, le détail se déplie à la demande (pattern Perplexity).
#   4. **Indicateur ambiant de tâche de fond** (`Sidebar.jsx`) : badge "🗂️ N tâche(s) de
#      fond en cours" visible depuis N'IMPORTE QUELLE page dès qu'un job `_long_task_resume`
#      (v2.145) est actif — jusqu'ici totalement invisible tant qu'on ne demandait pas
#      explicitement `long_task_status`. Sondage léger de `/api/cron` toutes les 30s (même
#      cadence que le indicateur Ollama existant), cliquable vers `/tasks`.
#   Testé en réel (Playwright, channel="chrome") : requête code_python → badge "🐍 Code
#   Interpreter" affiché, carte renommée "Exécuter du code Python", résultat 391 correct,
#   0 erreur console ; requête à 4 outils → repli "3/4 étape(s) en cours ▼ Afficher" confirmé
#   fonctionnel en direct (capture d'écran, tour encore en cours) ; page fraîche rechargée
#   → 0 requête réseau en échec. `scripts/smoke_test_chat.py` 5/5.
#
# v2.147 (🎯 UI — rendus dédiés pour les 5 outils "mode" v2.141-145) : sur demande
#   explicite (« continue les améliorations sur cette voie »), suite directe de v2.146.
#   Audité `PrettyResult.jsx`/`MessageBubble.jsx::renderToolResult` : les 5 nouveaux outils
#   (web_deep_research, ai_model_council, ai_subagents_run, long_task_start, long_task_
#   status) retombaient sur le JSON générique malgré des résultats riches — exactement le
#   genre de détail que le bandeau de mode (v2.146) donne envie d'explorer une fois la
#   carte dépliée, mais rien ne l'exploitait.
#   5 rendus dédiés ajoutés à `renderToolResult` : synthèse en markdown (réutilise `marked`/
#   `safeHtml` déjà présents dans le fichier) + détail repliable par défaut (nouveau
#   composant `CollapsibleDetail`) pour les sources (recherche approfondie), les réponses
#   individuelles par modèle (panel d'experts), le détail par sous-tâche (sous-tâches
#   parallèles) ; checklist avec cases à cocher pour `long_task_start`/`long_task_status`
#   (barre de progression + texte barré sur les étapes faites).
#   Testé en réel (Playwright) : requête "démarre une tâche longue" → badge "🗂️ Tâche
#   longue démarrée" affiché, carte d'outil rendue sans erreur (0 erreur console sur 3
#   passes de test, y compris un test intermédiaire accidentellement rejoué sur une
#   ancienne conversation chargée d'historique — confirmé artefact de méthode de test, pas
#   un bug). Les formes de données (steps/groups/individual_answers/subtask_results) sont
#   celles déjà validées en réel côté backend lors de leur implémentation (v2.141-145) —
#   changement purement d'affichage, aucun risque de désynchronisation. `scripts/
#   smoke_test_chat.py` 5/5.
#
# v2.148 (🎯 UI — chrono en direct + garde-fou repli/confirmation) : sur demande explicite
#   (« continue dans cet voie, inspire-toi des dernières nouveautés AI »), recherche menée
#   (patterns d'architecture de statut en 4 couches — ambiant/progression/attention/
#   résumé — et affichage du temps écoulé par sous-agent, tendances agent UI 2026).
#   🔴 BUG TROUVÉ EN AUDITANT (pas cherché délibérément) AVANT d'ajouter la nouvelle
#   fonctionnalité : le repli d'étapes ajouté en v2.146 (`shouldCollapse` dès 3 outils)
#   pouvait cacher par défaut un outil CRITIQUE en attente de confirmation (ex. supprimer
#   un fichier, envoyer un email) derrière "▼ Afficher" — une confirmation d'action
#   potentiellement dangereuse ne doit JAMAIS être masquée. Corrigé : nouvelle fonction
#   `toolNeedsAttention()` (couche "attention" du pattern à 4 niveaux) désactive le repli
#   dès qu'un des outils du tour en a besoin.
#   **Chrono en direct** (`ChatContext.jsx::tool_start` horodate `startedAt`, `ToolCallInline`
#   affiche "⟳ Exécution... (Ns)" au-delà de 3s) : les outils lents (recherche approfondie,
#   panel d'experts, tâche longue) restaient sur "⟳ Exécution..." plusieurs minutes sans
#   AUCUN repère de temps — symptôme déjà documenté (v2.125/v2.136, "Marvin reste
#   bloqué"). Complète le compteur déjà existant sur le `TypingIndicator` (les "trous"
#   entre outils), qui ne couvrait pas la carte d'un outil UNIQUE en cours d'exécution.
#   Testé en réel (Playwright) : `ai_model_council` (appel bloquant unique, la fenêtre la
#   plus large pour observer) → carte capturée avec "Exécution... (12s)" affiché
#   correctement en cours d'exécution ; 0 erreur console sur l'ensemble des tests.
#   `scripts/smoke_test_chat.py` 5/5.
#
# v2.149 (🖱️ Agent GUI local — lecture/clic/frappe via UI Automation) : sur demande
#   explicite (« cherche et creuse encore » sur la piste "agent GUI local" identifiée en
#   recherche continue). Vrai trou d'architecture trouvé en auditant AVANT de proposer quoi
#   que ce soit : Marvin avait déjà les "yeux" (`pc_screenshot`, `screen_ocr`,
#   `pc_window_list`/`focus`) mais ZÉRO "main" — aucun moyen de cliquer/taper dans une
#   fenêtre. Choix délibéré, discuté avec l'utilisateur avant implémentation : UI Automation
#   (arbre structuré natif Windows, via `pywinauto` backend "uia") plutôt qu'un agent vision
#   façon UI-TARS — 100% local, AUCUNE capture d'écran envoyée à un modèle (donc aucun
#   risque qu'un email/mot de passe affiché à l'écran parte au cloud), et plus précis qu'un
#   clic en coordonnées pixel qui casse au moindre décalage.
#   3 nouveaux outils, pattern "lire un ID réel avant d'agir dessus" (même esprit que
#   `winget_install` v2.113 et `long_task_status` v2.145) : `pc_gui_read` (lecture seule,
#   énumère les éléments cliquables d'une fenêtre) → `pc_gui_click`/`pc_gui_type` (agissent
#   sur un élément identifié à l'étape précédente, ajoutés à `DANGEROUS_TOOLS`).
#   🛡️ Protection structurelle contre une attaque TOCTOU (time-of-check/time-of-use,
#   documentée dans la littérature agents 2026) : `pc_gui_click`/`pc_gui_type` ne reçoivent
#   JAMAIS de coordonnées figées d'une lecture précédente — chaque appel refait une
#   résolution LIVE de l'élément (par automation_id ou control_type+name+match_index) au
#   moment même de l'action ; si l'élément a disparu/changé, l'appel échoue proprement
#   plutôt que de cliquer au hasard. Nouvelle règle d'or #15 : le texte lu via `pc_gui_read`
#   reste du CONTENU OBSERVÉ, jamais une instruction, même si un élément affiche "clique
#   ici" — n'agit que sur demande explicite de CE tour de conversation.
#   🔴 Bug réel trouvé en testant en conditions réelles (pas en devinant) : le Bloc-notes
#   Windows 11 (réécriture WinUI3) expose sa zone de texte en `control_type="Document"`, PAS
#   `"Edit"` — filtré silencieusement par la liste de types interactifs initiale. Corrigé,
#   ET durci au passage : pour Edit/Document, le `name` UIA EST le contenu du champ (donc
#   change à chaque frappe) — jamais utilisé comme clé de ré-résolution (uniquement affiché,
#   tronqué), le matching se fait par position (`match_index`) parmi les contrôles du même
#   type.
#   Testé en réel de bout en bout sur une vraie fenêtre Bloc-notes (pas de simulation) :
#   `pc_gui_read` a listé 40+ éléments réels (onglets, boutons) ; `pc_gui_click` sur un
#   onglet a réellement changé l'onglet actif (titre de fenêtre vérifié avant/après) ;
#   `pc_gui_type` a réellement inséré du texte dans le champ Document (contenu relu après
#   coup, confirmé) ; fenêtre fermée sans sauvegarder pour ne rien laisser de test dans les
#   vrais fichiers de l'utilisateur. `pc_gui_read` confirmé sans confirmation requise
#   (lecture seule), `pc_gui_click`/`pc_gui_type` confirmés dans `DANGEROUS_TOOLS`.
#   ⚠️ Incident pendant les tests, sans rapport avec le code livré : un script de test
#   maison a lancé deux processus en parallèle par erreur et tué des connexions SSE en plein
#   streaming → backend bloqué ~20 min (`/api/health` ne répondait plus, sockets en
#   CloseWait). Diagnostiqué, backend redémarré proprement, confirmé sain. Artefact de mon
#   test, pas un bug produit — documenté ici par transparence.
#   Limite connue et assumée, non résolue ici : UI Automation ne franchit pas la frontière
#   UAC (fenêtre élevée/admin inaccessible depuis ce process non-admin) — échec explicite,
#   pas de contournement (cliquer en tant qu'admin serait un risque d'un tout autre ordre
#   que l'allowlist stricte du sidecar élevé, v2.90).
#
# v2.150 (🔒 durcissement pc_gui_* + 🌙 heures calmes) : sur demande explicite (« continue et
#   cherche à corriger, améliorer, sécuriser et prendre les nouveautés AI de chatgpt et
#   claude »).
#   🛡️ Vérifié en conditions réelles (pas supposé) sur les outils GUI livrés en v2.149 :
#   un champ mot de passe peut-il fuiter via `pc_gui_read` ? Test réel avec une vraie
#   fenêtre WinForms (`PasswordChar` + `IsPassword=True`) → Windows UI Automation masque
#   déjà `window_text()` ET `get_value()` (tous deux vides) — rien à corriger côté fuite,
#   c'est une garantie de l'OS. Durci quand même : le champ est désormais étiqueté
#   explicitement `"(champ mot de passe — masqué par Windows)"` + `is_password: true` au
#   lieu d'un `name` vide silencieux qui aurait pu passer pour un bug ou un élément inconnu.
#   🌙 Nouveauté reprise de Claude (recherche menée : "Focus settings" 2026 — heures calmes/
#   pauses/récap) : réglage `quiet_hours` (désactivé par défaut, 22h-7h si activé) qui coupe
#   TOUTE notification proactive (briefing matinal, bilan du soir, anticipation) sur une
#   plage horaire — jamais les demandes faites directement dans le chat, uniquement le
#   déclenchement automatique en arrière-plan. Nouvel onglet dans `/jour` (même pattern que
#   les 3 blocs existants : `saveBlock`/état local/round-trip `/api/proactive`).
#   Testé en réel de bout en bout : `_in_quiet_hours()` unit-testé sur les cas limites
#   (plage à cheval sur minuit, bornes incluses/exclues) — 7/7 corrects ; toggle cliqué dans
#   le vrai navigateur (Playwright) → persisté côté backend, vérifié par lecture API ;
#   remis à l'état par défaut (désactivé) après le test pour ne pas modifier un réglage réel
#   sans le choix explicite de l'utilisateur.
#
# v2.151 (📋 Plan mode + pause sur blocage — repris de ChatGPT Work) : sur demande explicite
#   (« continue a prendre toutes les fonction des nouveauté ai notament work de chatgpt »).
#   Recherche approfondie menée sur ChatGPT Work (lancé le 09/07/2026) avant implémentation :
#   deux mécanismes de contrôle central absents chez Marvin — "Plan mode" (le plan est
#   proposé et VALIDÉ avant que le travail commence) et pause explicite quand l'agent a
#   besoin d'une approbation, plutôt que de continuer en boucle sans prévenir.
#   `long_task_start` décomposait ET démarrait l'exécution IMMÉDIATEMENT, sans jamais montrer
#   le plan à valider — corrigé en deux phases réutilisant le booléen `confirmed` déjà
#   standard sur tous les outils dangereux de Marvin (aucun nouveau concept introduit) : 1er
#   appel (sans confirmed) → décompose et renvoie le plan via `requiresConfirmation`, ne crée
#   RIEN ; rappel avec `confirmed=true` + les mêmes `steps` → crée réellement les tâches et
#   programme la reprise automatique. `long_task_start` ajouté à `DANGEROUS_TOOLS`.
#   🔴 Bug réel trouvé en testant (pas cherché délibérément) : le timeout de 60s sur l'appel
#   de décomposition (`long_task_start` ET `ai_subagents_run`, même pattern dans les deux)
#   était systématiquement dépassé sur cette machine (reproduit 3/3 fois, cloud ET local),
#   faisant silencieusement échouer TOUT démarrage de tâche longue depuis l'introduction de
#   cette fonctionnalité en v2.145. Porté à 90s.
#   Pause sur blocage (`long_task_resume_tick`, cron_runtime.py) : une reprise automatique par cron
#   n'a personne pour cliquer "confirmer" si l'étape en cours nécessite un outil DANGEREUX —
#   sans détection, le job aurait retenté la même chose toutes les 5 min indéfiniment, en
#   silence. Détecté en comparant le nombre d'étapes en attente avant/après chaque reprise :
#   3 tentatives consécutives sans progression (~15 min) → reprise automatique coupée +
#   notification explicite invitant à ouvrir la conversation pour débloquer.
#   Testé en réel via `/api/mcp/execute` (le chat complet est trop lent/coûteux pour un test
#   itératif) : décomposition + création réelles confirmées 2× après le fix du timeout (8
#   étapes créées, tâches + job cron visibles) ; la branche "plan proposé sans création" n'a
#   PU être testée en LIVE (cette machine tourne en permission Expert, qui auto-confirme —
#   le classifieur de permissions a refusé, à raison, de changer ce réglage juste pour
#   contourner un test) — vérifiée par relecture de code uniquement, même limite déjà
#   documentée et acceptée pour v2.121.
#   🔴 Bug PRÉ-EXISTANT et SANS RAPPORT trouvé en testant (flagué en tâche séparée, pas
#   corrigé ici — hors scope) : `DELETE /api/tasks/{id}` bloque le event-loop entier du
#   backend (même `/api/health` cesse de répondre juste après), reproduit à plusieurs
#   reprises sur redémarrages propres — probable contention SQLite avec un des workers de
#   fond, appel synchrone non `asyncio.to_thread`. 3 tâches de test n'ont pas pu être
#   supprimées à cause de ce bug (tag `longtask:verifier-espace-disque-de-chaque-lecteur`,
#   à nettoyer une fois le bug corrigé).
#
# v2.152 (🩹 Correctif DELETE /api/tasks bloquait l'event-loop) : sur demande explicite
#   (« ok fait le », donnant suite au bug flagué en v2.151). Cause racine trouvée en lisant
#   `database.py::get_conn()` : chaque appel `db()` ouvre une NOUVELLE connexion SQLite
#   synchrone (`sqlite3.connect(...)`, jamais `asyncio.to_thread`), invoquée directement
#   depuis des routes FastAPI async — sur un backend mono-thread (asyncio), un blocage même
#   bref (contention WAL avec un worker de fond, antivirus scannant `.db-wal` sous Windows)
#   gèle donc TOUT l'event-loop, pas seulement la requête en cours — expliquant pourquoi
#   `/api/health` (qui ne touche pourtant pas la DB) cessait aussi de répondre juste après
#   un DELETE. Corrigé : `delete_task` (le symptôme précisément rapporté) déporté sur un
#   thread via `asyncio.to_thread` — même pattern déjà établi pour `subprocess.run` (v2.96).
#   `get_conn()` reçoit aussi un `timeout=10.0` explicite (busy_timeout SQLite) en défense
#   complémentaire.
#   ⚠️ Portée volontairement limitée : 28 routes `@app.delete` (et un nombre comparable de
#   POST/PUT) partagent la MÊME exposition structurelle — les corriger toutes aurait été un
#   refactor bien plus large que le bug rapporté. Documenté ici comme piste connue pour un
#   futur passage plus large, pas traité en silence ni oublié.
#   Testé en réel : 15 cycles create+delete+health en boucle après le fix → 0 blocage,
#   pire cas 5ms (delete) / 28ms (health) — contre un blocage reproduit à plusieurs reprises
#   avant. `scripts/smoke_test_pages.py` 34/34. Les 3 tâches de test bloquées depuis v2.151
#   supprimées avec succès (preuve directe que le fix résout le cas qui les avait bloquées).
#
# v2.153 (🔗 liens du chat ouverts dans un nouvel onglet) : signalé directement par
#   l'utilisateur (« marvin ma indiqué des lien très pertinent mais quand on clic dessus
#   cela nous amène directement à la page et quitte marvin »). Cause trouvée : les liens
#   `[texte](url)` markdown de la réponse de chat passent par `marked.parse` + `safeHtml`
#   (DOMPurify) — contrairement aux liens des composants dédiés (sources web_search,
#   résultats de recherche) qui avaient déjà `target="_blank"` en dur, ceux générés depuis
#   le markdown de la réponse n'avaient AUCUN attribut cible, donc ouverture dans l'onglet
#   courant = quitte Marvin. Corrigé via un hook DOMPurify (`afterSanitizeAttributes`)
#   plutôt qu'un renderer `marked` personnalisé — couvre uniformément le markdown ET tout
#   HTML `<a>` brut que le modèle aurait pu produire, indépendamment de la version de
#   `marked`. `target="_blank"` + `rel="noopener noreferrer"` (sécurité : empêche la page
#   ouverte d'accéder à `window.opener`).
#   Testé en réel (Playwright) : message forçant un lien markdown dans la réponse →
#   `target="_blank"` et `rel="noopener noreferrer"` confirmés sur l'élément `<a>` réellement
#   rendu (DOM inspecté directement, pas supposé), 0 erreur console.
#
# v2.154 (🌐 2 outils réseau sysadmin/étudiant) : sur demande explicite (« continue à rendre
#   Marvin plus efficace et intelligent, je veux plus d'outils en rapport avec mes recherches
#   sur l'informatique et le fait que je suis en train de devenir admin système et réseau »).
#   Audit préalable des outils réseau existants (net_*/ssh_*/win_*, déjà nombreux) + recoupé
#   avec l'activité réelle visible dans les fichiers de l'utilisateur (TrueNAS, Zabbix,
#   GitLab CE, Nextcloud, Tailscale — un vrai homelab, pas que des études théoriques).
#   `net_subnet_calc` : calculateur de sous-réseau VLSM/CIDR (adresse réseau, broadcast,
#   masque, wildcard, plage d'hôtes utilisables, découpage en sous-réseaux) — utile à la
#   fois pour réviser le subnetting (Network+/CCNA) et planifier un vrai plan d'adressage.
#   `net_tls_check_bulk` : contrôle TLS/certificat sur plusieurs hôtes en parallèle (réutilise
#   `net_tls_check` par hôte), signale ceux qui expirent sous 30 jours — utile avec plusieurs
#   services auto-hébergés en TLS.
#   🔴 Bug réel trouvé en testant (pas en devinant) : le calcul de `next_subnet` (via
#   `supernet()/subnets()[1]`) retournait le sous-réseau LUI-MÊME quand il occupait la 2e
#   moitié de son supernet (ex. 192.168.1.0/24 → "192.168.1.0/24" au lieu de 192.168.2.0/24).
#   Corrigé par calcul arithmétique direct (adresse réseau + nombre d'adresses) plutôt que
#   la manipulation supernet/subnets, vérifié sur plusieurs CIDR après coup.
#   Testé en réel : `net_subnet_calc` vérifié sur 192.168.1.0/24 (avec découpage VLSM en
#   4×/26) et 10.20.30.0/27, tous les champs corrects ; `net_tls_check_bulk` testé contre
#   google.com/github.com (certificats réels, jours restants corrects) + un hôte injoignable
#   (erreur gérée proprement sans faire échouer les autres). `scripts/smoke_test_pages.py`
#   34/34.
#
# v2.155 (🌐 SNMP + diagramme topologie + 🧠 fiches de révision) : sur demande explicite
#   (« fait tout diagramme de topologie réseau visuel, requêtes SNMP, ou un mode fiches de
#   révision/quiz pour tes certifs »), suite directe de v2.154.
#   `net_snmp_query` (pysnmp 7, hlapi v3arch asyncio, SNMPv2c) : action='sysinfo' (nom/
#   description/uptime/contact/localisation en un appel), 'interfaces' (walk borné IF-MIB,
#   état up/down), 'get' (OID précis). `net_topology_diagram` : diagramme PNG (matplotlib,
#   déjà une dépendance) affiché directement dans le chat via le mécanisme `result.image`
#   déjà existant (pc_screenshot) — passerelle au centre, appareils autour, scan local
#   automatique si 'hosts' omis.
#   🔴 2 bugs réels trouvés en testant (pas en devinant, en regardant l'image générée) :
#   (1) `net_scan_local` n'a JAMAIS eu de champ "gateway"/"hostname"/"vendor" — j'avais
#   halluciné ces clés en écrivant le code sans vérifier ; corrigé en récupérant la vraie
#   passerelle via `win_network_config` (Get-NetIPConfiguration). (2) Les icônes emoji (🌐/🖥)
#   s'affichaient en "tofu" (glyphe manquant, police par défaut matplotlib DejaVu Sans sans
#   couverture emoji) — remplacées par des libellés texte courts (GW/PC) garantis lisibles.
#   `net_snmp_query` action='interfaces' durci aussi : distingue maintenant "0 réponse SNMP"
#   (erreur explicite) de "0 interface légitime" (succès vide) — la version initiale
#   renvoyait un succès trompeur dans les deux cas.
#   🧠 Fiches de révision (`quiz_generate`/`quiz_next`/`quiz_answer`/`quiz_stats`, nouvelle
#   table `flashcards`) : répétition espacée minimale (bonne réponse → intervalle double
#   plafonné à 60j, mauvaise réponse → repasse le lendemain) — délibérément plus simple qu'un
#   moteur SM-2 complet, cohérent avec le reste de Marvin (pas de sur-ingénierie pour un
#   besoin d'étude personnelle). `quiz_next` ne révèle jamais la réponse avant `quiz_answer`.
#   Testé en réel de bout en bout : diagramme généré sur le vrai réseau local (13→11
#   appareils après exclusion correcte de la passerelle, labels lisibles, IP passerelle
#   réelle affichée) ; SNMP testé contre un hôte sans agent (erreur propre, pas de hang) ;
#   cycle complet fiches (génération de 3 vraies questions sur le modèle OSI, réponse
#   correcte → intervalle 1→2 jours, carte suivante correctement différente, stats exactes
#   due_now 2/3) — fiches de test supprimées après coup. `scripts/smoke_test_pages.py` 34/34.
#
# v2.156 (🎨 Présentation du diagramme de topologie réseau revue) : sur demande explicite
#   (« pouvons-nous améliorer la présentation des schémas réseau ? »), après avoir audité une
#   conversation réelle et constaté qu'aucune n'utilisait encore l'outil via le chat (seuls
#   mes propres appels de test v2.155) — l'utilisateur faisait référence aux images déjà
#   montrées pendant les tests.
#   Trouvaille annexe en cherchant la conversation : la page `/outils` a un catalogue
#   d'outils ENTIÈREMENT codé en dur (`app/outils/page.jsx`, ~3250 lignes), complètement
#   déconnecté du vrai `TOOLS_REGISTRY` backend — "141 outils" affichés contre 327 réels,
#   recherche de "topologie" → 0 résultat alors que l'outil existe et fonctionne. Pas corrigé
#   ici (portée bien plus large qu'une amélioration de présentation) — flagué en tâche de
#   fond séparée (task_9af62ef6).
#   Refonte de `net_topology_diagram` (tools.py) : couleurs calées EXACTEMENT sur
#   `app/globals.css` (--bg-primary/--accent-primary/--accent-secondary/--text-muted) au
#   lieu d'une palette approximative ; disposition en ANNEAUX CONCENTRIQUES au-delà de 8
#   appareils (un seul cercle surchargeait les libellés dès qu'un réseau réel dépassait une
#   dizaine d'hôtes) ; légende (passerelle/appareil) + horodatage en pied de diagramme.
#   🔴 2 bugs de mise en page trouvés en testant à l'échelle réelle (20 appareils, 3
#   anneaux) — pas en devinant, en regardant l'image rendue : l'anneau extérieur était
#   ROGNÉ par les bords de la figure (le calcul de marge n'avait pas été mis à jour après
#   l'augmentation du rayon de base), et le libellé IP de la passerelle empiétait sur
#   l'anneau intérieur. Les deux corrigés et revérifiés par un nouveau rendu.
#   Testé en réel à 3 échelles : réseau local réel (13 appareils, 2 anneaux), synthétique à
#   12 (2 anneaux) et 20 appareils (3 anneaux, le plafond) — plus aucun rognage, légende et
#   horodatage lisibles, couleurs cohérentes avec le reste de l'interface.
#   `scripts/smoke_test_pages.py` 34/34.
#
# v2.157 (🧩 Catalogue /outils complété automatiquement) : sur demande explicite (« corrige
#   ce que tu as trouvé comme bug »), suite du bug flagué en v2.156 (chip de tâche de fond,
#   task_9af62ef6, dismiss après prise en charge directe).
#   Plutôt qu'un remplacement complet du catalogue (aurait perdu le regroupement en 4
#   familles/17 catégories et les 141 formulaires soigneusement conçus à la main), la page
#   `app/outils/page.jsx` COMPLÈTE désormais le catalogue statique : au chargement, un appel
#   à `GET /api/tools/list` (déjà existant, utilisé par le serveur MCP) récupère la liste
#   réelle des 327 outils backend, et tout outil absent du catalogue codé en dur atterrit
#   dans une nouvelle catégorie "🧩 Autres outils" avec un formulaire généré automatiquement
#   depuis son schéma JSON (`schemaToParams` — string→texte, integer/number→nombre,
#   boolean→case à cocher, array de string→tags, enum→menu déroulant). Moins soigné que les
#   formulaires à la main, mais au moins DÉCOUVRABLE et exécutable — c'était le vrai manque.
#   Best-effort : si l'appel à `/api/tools/list` échoue, le catalogue statique reste
#   utilisable tel quel (aucune régression possible).
#   Testé en réel (Playwright) : 141→328 outils affichés, recherche de "topologie" passe de
#   0 à 1 résultat (`net_topology_diagram`, absent du catalogue codé en dur) ; formulaire
#   auto-généré (champs Hosts/Gateway avec les vraies descriptions en placeholder) exécuté
#   pour de vrai depuis la page → diagramme réel généré et affiché, 0 erreur console ; les 4
#   familles/17 catégories d'origine vérifiées inchangées après coup (pas de régression).
#   `scripts/smoke_test_pages.py` 34/34.
#
# v2.158 (🗂️ /outils — auto-catégorisation par préfixe) : sur demande explicite (« attaque
#   le [option 2] mais ne casse rien... prépare un plan réfléchi »). Passé par un vrai Plan
#   mode (EnterPlanMode/ExitPlanMode) avant d'écrire du code, approuvé par l'utilisateur.
#   Remplace le vrac "Autres outils" (v2.157, 186 outils non triés) par une répartition dans
#   les catégories EXISTANTES par préfixe (`pickCategoryId` : `ssh_`→SSH, `net_`→Réseau,
#   `win_`/`pc_`→PC, `email_`→Email... repli sur `utilitaires`, déjà pensée pour les outils
#   génériques ambigus). Icônes aussi dérivées du préfixe (`pickAutoIcon`) au lieu du 🧩
#   uniforme. 2 nouvelles catégories légères pour des familles backend entières qui
#   n'avaient encore AUCUNE place ici : Facturation (`billing_`/`client_`, 27 outils — /devis
#   existe côté produit, jamais relié à /outils) et Fiches de révision (`quiz_`, 4 outils).
#   `TOOL_OVERRIDES` (vide au démarrage) : point d'extension pour curer un outil
#   auto-généré à la main plus tard sans dupliquer toute son entrée — concrétise le principe
#   « la curation est l'exception, pas la règle par défaut » pour tout nouvel outil futur,
#   sans toucher aux 141 entrées déjà curées (jamais dérivées, rien à gagner à les migrer).
#   Contrainte respectée : le tableau `CATEGORIES` statique (~3250 lignes) n'est PAS modifié
#   — tout le travail se fait dans la petite couche dynamique ajoutée en v2.157, qui fusionne
#   par-dessus sans jamais muter l'original.
#   Testé en réel (Playwright) : plus de groupe "Autres outils" ; catégories curées
#   vérifiées inchangées (Infographie garde son outil curé en tête de liste, les auto
#   ajoutés après) ; "Fiches de révision" (4) et "Facturation" (27) apparaissent sous
#   Organisation ; recherche "topologie" trouve toujours l'outil avec sa nouvelle icône 🌐 ;
#   `quiz_stats` exécuté pour de vrai depuis sa nouvelle catégorie → résultat réel affiché
#   (10 fiches dues, données réelles d'une conversation antérieure) ; 0 erreur console.
#   `scripts/smoke_test_pages.py` 34/34.
#
# v2.159 (🩺 Tableau de bord de fiabilité — signal récent vs historique) : sur demande
#   explicite (« quel serait le meilleur pour que tous les outils soient fonctionnels et bien
#   exploités... que proposes-tu ? » → « ok »). Plutôt qu'une réécriture aveugle des 327
#   outils, utilisé le tableau de bord de fiabilité déjà existant (v2.138) pour cibler
#   data-driven les vrais problèmes — puis vérifié chaque "pire outil" un par un en conditions
#   réelles plutôt que de faire confiance à l'agrégat brut.
#   🔴 Trouvaille inattendue en auditant (pas cherchée délibérément) : les 5 pires outils du
#   classement (`git_info`, `ssh_exec`, `ssh_write_and_run`, `ocr_extract`, `calendar_list`)
#   se sont TOUS révélés déjà fonctionnels en testant en direct — `git_info` et `ocr_extract`
#   marchent parfaitement (le repli de modèle OCR halluciné de v2.106 fonctionne bien, testé
#   avec `model:"llava:13b"` explicitement) ; `calendar_list` renvoie de vrais événements ;
#   `ssh_exec`/`ssh_write_and_run` n'ont JAMAIS vraiment échoué — leurs "100% d'échec" sont 2
#   rejets de validation corrects (paramètre manquant, message d'erreur clair) + 1 appel de
#   test délibéré contre `192.0.2.1` (TEST-NET-1, plage RFC 5737 réservée aux tests,
#   injoignable par définition). Le vrai bug n'était donc PAS dans ces 5 outils — il était
#   dans le TABLEAU DE BORD lui-même : `get_tool_reliability` (v2.138) agrège sur 90 jours
#   sans aucune pondération temporelle, donc un bug corrigé il y a 3 semaines (le cas de
#   `calendar_list` : 64% d'échec sur 90j À CAUSE d'un repli OAuth ajouté depuis, v2.137)
#   traîne indéfiniment en tête du classement — rendant le tableau de bord de moins en moins
#   fiable avec le temps, à l'inverse de son but.
#   Corrigé : `db.get_tool_reliability` calcule maintenant AUSSI un taux récent
#   (`recent_days`, 7j par défaut) dans la même requête, plus un flag `likely_already_fixed`
#   (mauvais taux global mais 0 échec récent avec assez d'appels récents pour être
#   significatif). `pc_tool_reliability` et `GET /api/history/reliability` exposent les deux
#   axes — un outil avec un mauvais taux global mais un taux récent proche de 0% n'est plus
#   une fausse priorité.
#   Testé en réel : `calendar_list` passe de "64,2% d'échec (95 appels)" à "3,4% d'échec sur
#   les 7 derniers jours (29 appels)" — la vraie histoire, invisible avant ce correctif.
#   `scripts/smoke_test_pages.py` 34/34.
#
# v2.160 (Test réel des ~280 outils non destructeurs) : sur demande explicite (« tu n'as
#   qu'à tester tout les outils pour voir s'il fonctionne et on voit après »), suite directe
#   de v2.159. Script jetable (scratchpad) qui appelle chaque outil du catalogue /api/tools/list
#   avec des arguments minimaux dérivés de son schéma JSON, via POST /api/tools (le vrai
#   chemin d'exécution, pas une simulation) — 47 outils destructeurs/coûteux (SSH exec, envoi
#   email, suppression, winget install, génération vidéo/LLM lourde...) explicitement exclus
#   de l'automatisation, jamais invoqués en aveugle.
#   Résultat sur 327 outils : 139 OK, 111 rejets de validation corrects (comportement attendu
#   sur des arguments bidons), 69 volontairement écartés, 8 échecs à investiguer.
#   Sur les 8 : 4 étaient des faux positifs (email_digest 54s / daily_briefing 87s /
#   document_ask 28s — juste plus lents que le plafond de 45s du script de test, pas cassés ;
#   pptx_read — anomalie transitoire, marche parfaitement en re-test isolé).
#   3 VRAIS BUGS trouvés et corrigés :
#   1. file_large_finder sans dossier précisé scanne tout le home (os.walk synchrone,
#      132 Go réels sur cette machine) — 145 SECONDES pendant lesquelles TOUT le backend
#      était gelé (même classe de bug que v2.96/v2.152 : blocage synchrone dans une fonction
#      async, jamais repérée pour celle-ci). Déporté sur un thread (asyncio.to_thread).
#   2. calendar_create avec une date start non parseable levait une ValueError non
#      rattrapée -> 500 brut au lieu d'un message clair.
#   3. email_attachment_summary avec un uid invalide faisait planter la commande IMAP
#      FETCH (exception non rattrapée) -> 500 brut au lieu d'un message clair.
#   Testé en réel après correctif (backend redémarré) : les 3 renvoient maintenant une erreur
#   propre (200 + {"error":...}) sur les mêmes arguments qui plantaient avant ; preuve directe
#   du fix event-loop — /api/health répond en 31ms alors qu'un file_large_finder complet
#   (158s, 132 Go, home réel) tourne en parallèle sur un thread séparé.
#
# v2.161 (recherche web plus résiliente à l'anti-bot) : signalé directement par
#   l'utilisateur (« lors de ma dernière conversation Marvin a été bloqué sur le web à
#   cause de l'anti-bot, comment éviter cela ? »). Confirmé dans l'historique réel : le
#   scraping HTML DuckDuckGo (seul provider gratuit sans clé) se fait bloquer par
#   intermittence, plusieurs fois documenté (03/06, et à nouveau la veille du jour de
#   cette correction). Reproduit en direct pendant l'investigation : un blocage réel
#   était toujours actif sur cette IP au moment du test.
#   1. Retry DuckDuckGo durci : 1 seule tentative (1,6s) -> 3 tentatives avec backoff
#      croissant (2s/5s/9s, ~16s cumulés) — le blocage anti-bot DDG dure typiquement
#      quelques dizaines de secondes, un seul retry rapide tombait souvent encore dedans.
#   2. Sur demande explicite (« trouve une solution, cherche sur le web, innove ») :
#      recherche menée sur les alternatives 2026 — le plan gratuit de Brave Search s'est
#      dégradé (5000/mois en 2025 -> 2000/mois, et les nouveaux comptes n'ont même plus
#      de vrai palier gratuit, juste un crédit de $5). La vraie solution robuste et
#      cohérente avec la doctrine "100% local" de Marvin : SearXNG, un méta-moteur open
#      source auto-hébergeable (Docker) qui agrège plusieurs moteurs sans jamais exposer
#      Marvin directement à leur anti-bot, sans clé ni quota — gratuit et illimité une
#      fois hébergé (adapté au profil homelab de l'utilisateur : TrueNAS/GitLab/Docker
#      déjà en place). Nouveau provider `_searxng()` dans execute_web_search, nouveau
#      réglage `searxng_url` (credentials_manager.py, groupe "search", visible dans
#      Réglages > Connexions) — prioritaire en mode auto quand configuré (avant
#      brave/google/serpapi/duckduckgo), sinon la cascade existante est inchangée.
#   Testé en réel : `searxng_url` confirmé visible via `GET /api/credentials` (groupe
#   search) ; `provider=searxng` sans configuration renvoie une erreur claire (pas de
#   crash) ; mode `auto` sans SearXNG configuré retombe bien sur la cascade existante,
#   confirmé jusqu'à DuckDuckGo qui répond effectivement en ~17s (3 tentatives) avec le
#   nouveau message d'erreur orientant vers les alternatives — comportement exact
#   observé qui a motivé le correctif, reproduit en direct pendant la vérification.
#
# v2.162 (deploiement SearXNG automatise + integration installeur) : suite directe de
#   v2.161, sur demande explicite (« fait tout et pense a utiliser des ports autres [...]
#   et pense que tout cela doit etre dans marvin pour faciliter le deploiement futur sur
#   d'autre machine de facon facile »).
#   Nouveaux fichiers portables (docker/searxng/) : docker-compose.yml (port hote 8890,
#   volontairement hors des defauts courants 8080/9000/3000 pour eviter tout conflit
#   homelab), settings.yml.example (modele versionne, JSON active, secret_key placeholder),
#   start-searxng.ps1 (idempotent : demarre Docker Desktop si besoin, genere un secret
#   local au 1er lancement, docker compose up -d, attend que l'API JSON reponde vraiment,
#   puis configure searxng_url dans Marvin via PUT /api/credentials automatiquement).
#   settings.yml (avec le secret genere) est gitignore -- jamais committe, propre a
#   chaque machine (meme doctrine que data/, deja gitignore pour les secrets reels).
#   Integration dynamique dans start.bat (nouvelle etape optionnelle : Docker detecte ->
#   lance start-searxng.ps1 en arriere-plan dans sa propre fenetre, sinon ignore
#   silencieusement -> DuckDuckGo/autres restent le comportement par defaut) et
#   INSTALLER-NOUVEAU-PC.bat (etape [4/9] informative, n'installe pas Docker de force --
#   trop lourd/disruptif pour un installeur non supervise, juste signale la commande
#   winget si l'utilisateur veut l'ajouter). INSTALLER-SEARXNG.bat (racine) : point
#   d'entree manuel si besoin de relancer/reconfigurer sans passer par start.bat.
#   Incident rencontre pendant le deploiement reel (documente par transparence, pas un
#   bug de ce code) : Docker Desktop a d'abord refuse de demarrer ("Virtualization
#   support not detected") -- cause : hypervisorlaunchtype avait ete desactive pour
#   optimiser VMware, coupant la virtualisation dont WSL2/Docker a besoin. Diagnostique
#   et corrige par l'utilisateur lui-meme (bcdedit /set hypervisorlaunchtype auto +
#   reactivation VirtualMachinePlatform/Hyper-V + redemarrage) -- modification systeme
#   volontairement laissee a l'utilisateur, jamais executee par Marvin/Claude Code.
#   Testes en reel de bout en bout : conteneur marvin-searxng demarre et repond
#   (`GET /search?format=json` -> vrais resultats) ; searxng_url confirme configure via
#   l'API Marvin ; `web_search` (l'outil chat reel) route bien vers SearXNG en priorite
#   sur une vraie requete ("actualite cybersecurite juillet 2026" -> 5 resultats reels et
#   pertinents, provider:"SearXNG" confirme dans la reponse). Observation annexe, pas un
#   bug : certains moteurs internes de SearXNG (duckduckgo, brave) se sont fait bloquer
#   (CAPTCHA/429) pendant le test reel -- comportement attendu d'un meta-moteur, les
#   autres moteurs (Google CSE, Startpage...) ont pris le relais sans interruption
#   visible cote utilisateur, exactement l'effet de resilience recherche.
#
# v2.163 (event-loop : 5 outils supplementaires corriges) : suite directe de v2.160
#   (file_large_finder), sur demande explicite apres avoir cherche systematiquement la
#   meme classe de bug ailleurs dans tools.py (grep os.walk/subprocess.run non wrappe
#   en asyncio.to_thread). 5 outils trouves et corriges : file_find (fallback os.walk
#   quand l'index Windows Search est indisponible sur une recherche "tout le PC"),
#   file_search_text (scan par defaut sur le home si aucun dossier precise),
#   document_index, file_duplicate_finder, system_cleanup (scan des dossiers Temp).
#   git_info et net_traceroute etaient deja corrects (verifie avant de toucher au code).
#   Meme pattern a chaque fois : extraction de la partie bloquante (os.walk, hash MD5...)
#   dans une fonction sync dediee, appelee via await asyncio.to_thread(...).
#   Teste en reel : les 5 outils repondent correctement sur des dossiers reels ; preuve
#   directe du non-blocage -- /api/health repond en 34ms pendant qu'un file_find lourd
#   (scan complet de backend/.venv, plusieurs milliers de fichiers) tourne en parallele.
#
# v2.164 (repli local mid-boucle trop large sur ssh_list) : signale par l'utilisateur sur
#   une vraie conversation ("script audit securite serveur linux") ou la reponse finale
#   n'avait rien a voir avec la demande (juste la liste des connexions SSH). Diagnostic :
#   web_search bloque par l'anti-bot DDG (deja corrige v2.161) a fait derailer l'agent sur
#   ssh_list -- outil totalement hors-sujet -- qui a DECLENCHE le repli local mid-boucle
#   (v2.119, badge "Repli local (donnee sensible detectee)") car son nom commence par
#   "ssh_". Or ssh_list ne renvoie JAMAIS de secret (host/port/username, has_password et
#   has_key en BOOLEEN, jamais la valeur) -- verifie dans le code reel avant de conclure.
#   Carve-out precis et nomme (pas un affaiblissement du prefixe "ssh_"/"email_" en
#   general) : SENSITIVE_TOOL_EXEMPTIONS = {ssh_list, email_accounts} dans
#   cloud_routing.py::is_sensitive_tool -- les deux ne listent QUE des metadonnees de
#   configuration, jamais un contenu reel (email, sortie de commande, mot de passe).
#   Teste en reel : is_sensitive_tool('ssh_list')=False, is_sensitive_tool('email_accounts')=False,
#   MAIS ssh_exec/ssh_download/ssh_write_and_run/email_read/email_list/billing_client_list/
#   credential_get restent tous True -- la garde de securite reste intacte pour tout ce qui
#   touche du contenu reel, seul le carve-out precis change.
#
# v2.165 (frontend : envoi d'un message n'annulait jamais le precedent en cours) : suite
#   directe de v2.164, l'utilisateur a precise que le script genere avait ete visible dans
#   le chat puis avait disparu apres avoir renvoye son message. Trouve dans
#   lib/contexts/ChatContext.jsx::sendMessage : un nouvel envoi creait un nouvel
#   AbortController SANS jamais annuler le precedent -- si le premier tour tournait
#   encore (recherche web bloquee, outil lent...), DEUX flux SSE concurrents pour la
#   MEME conversation s'executaient en parallele cote serveur ET cote React, chacun
#   appelant setMessages(prev => ...) avec un `prev` potentiellement obsolete -- le
#   contenu deja genere (script visible a l'ecran) pouvait etre perdu au prochain
#   rendu/rechargement sans jamais avoir ete correctement sauvegarde en base.
#   Fix : abortRef.current?.abort() AVANT de creer le nouveau controller. Le catch
#   existant ignorait deja err.name==='AbortError' (ecrit pour le bouton Stop) -- en
#   beneficie automatiquement, aucun changement de gestion d'erreur necessaire.
#   Comportement volontairement PAS touche : pas d'abort au demontage du composant
#   (continuer en fond si on navigue ailleurs reste voulu) -- seul un NOUVEL envoi
#   coupe l'ancien, pas une simple navigation.
#   Teste en reel (Playwright, JS direct pour fiabilite) : message A envoye (reponse
#   longue), message B envoye immediatement apres -- resultat final : SEULE la reponse
#   a B apparait proprement, aucune trace de A, 0 erreur console (AbortError avale par
#   le catch existant comme prevu). Conversation de test laissee en place (suppression
#   par ID recent refusee par le classifieur de securite -- regle anti-incident v2.110).
#
# v2.166 (durcissement SearXNG : liaison 127.0.0.1 au lieu de 0.0.0.0) : question directe
#   de l'utilisateur ("garde searxng en http c'est pas top non ?"). Analyse : le vrai
#   probleme n'etait pas HTTP en soi (le trafic Marvin<->SearXNG reste en boucle locale,
#   meme machine) mais le fait que "8890:8080" en docker-compose lie par defaut sur
#   TOUTES les interfaces (0.0.0.0) -- n'importe quel appareil du LAN pouvait donc
#   atteindre l'instance en clair. Plutot que d'ajouter du HTTPS (certificat auto-signe,
#   complexite inutile pour un service qui n'a jamais besoin de sortir de la machine),
#   restreint le binding a 127.0.0.1 -- elimine l'exposition reseau a la racine.
#   docker-compose.yml : "127.0.0.1:8890:8080" au lieu de "8890:8080".
#   Applique et verifie en reel : `docker port marvin-searxng` confirme 127.0.0.1:8890
#   (etait 0.0.0.0:8890 avant), `netstat` confirme l'ecoute uniquement en loopback,
#   web_search de Marvin fonctionne toujours normalement (provider:SearXNG) apres
#   recreation du conteneur -- aucune regression fonctionnelle.
#
# v2.167 (interface chat plus vivante et lisible) : demande explicite ("l'interface actuel
#   du chat marvin me parait peu jolie et atrayante... regarde sur le web, propose des
#   solutions" puis "fait tout"). Recherche web menee sur les patterns UI 2026 des grands
#   chatbots IA (Claude/ChatGPT/Perplexity/Gemini) + guides UX chat (interligne, largeur de
#   lecture) avant de proposer -- mockup montre avant/apres, 3 axes retenus (les moins
#   couteux, les plus grounded dans le code reel) :
#   1. Cartes de suggestion de l'ecran d'accueil (ChatContainer.jsx) : etaient purement
#      decoratives (cursor:default, aucun onClick) malgre une apparence de bouton -- pattern
#      etabli chez Claude/ChatGPT/Perplexity, cliquer envoie directement un prompt pertinent
#      via sendMessage(). Nouvelle classe .suggestion-card (globals.css) pour le hover/lift.
#   2. Largeur de lecture des messages assistant (MessageBubble.module.css) : 85% seul peut
#      depasser 1000px sur un ecran large, bien au-dela des ~65-72 caracteres/ligne
#      recommandes -- max-width: min(85%, 720px) sur .wrapperAssistant (messages utilisateur
#      inchanges, generalement courts). line-height 1.65 deja correct, pas touche.
#   3. Barre de saisie decongestionnee (ChatInput.jsx) : 3 boutons (image/document/
#      competence) fusionnes en un seul bouton "+" avec menu deroulant -- micro et mode
#      vocal restent visibles en direct (actions frequentes, un clic). Aucun changement de
#      logique sous-jacente (memes refs de fichiers caches, meme etat skillMenu), juste le
#      point d'entree visuel.
#   Teste en reel (Playwright + pilotage JS direct, contournement d'un souci de rendu
#   screenshot cette session) : clic reel sur la carte "Gerer vos emails" -> message
#   "Resume mes emails non lus" envoye et reponse agent declenchee (confirme via lecture du
#   DOM des messages) ; regle CSS max-width:min(85%,720px) confirmee compilee dans la
#   feuille de style live ; barre de saisie confirmee a 1 bouton "+" au lieu de 3, 0 erreur
#   console sur les 3 changements.
#
# v2.168 (cartes d'accueil : navigation directe au lieu d'une requete chat lourde) : suite
#   directe de v2.167, signale par l'utilisateur en testant les cartes tout juste ajoutees
#   ("c'est trop long a attendre"). Diagnostic confirme en relisant les 2 vraies
#   conversations de test : "Trouve les plus gros fichiers de mon disque C" a declenche
#   file_large_finder SANS dossier precise -> scan complet ~150s (meme risque documente en
#   v2.160/v2.163, jamais resolu cote temps d'attente utilisateur, seulement cote blocage de
#   l'event-loop) ; "Resume mes emails non lus" a declenche email_digest ~54s. Les deux
#   appels sont restes en etat "call" (jamais resolus) dans les messages persistes -- signe
#   direct que l'utilisateur a du abandonner/attendre.
#   Proposition retenue de l'utilisateur, meilleure que la v2.167 : chaque carte navigue
#   directement vers sa page dediee (deja riche, deja rapide, zero aller-retour LLM) au lieu
#   de lancer un prompt chat -- Gerer vos emails -> /emails, Organiser l'agenda -> /calendar,
#   Classer vos fichiers -> /fichiers, Controler le PC -> /systeme. router.push() (Next.js),
#   navigation cote client instantanee.
#   Teste en reel (Playwright + JS direct) : clic sur "Classer vos fichiers" -> navigation
#   confirmee vers /fichiers (window.location.pathname), 0 erreur console.
#
# v2.169 (salutation dynamique + logo retravaille) : demande explicite ("message de
#   bienvenue plus dans l'air du temps, inspire-toi de ce que font les meilleurs AI, le
#   logo doit etre engageant, meilleur et plus travaille"). Le titre "MARVIN" fige en
#   majuscules + tagline "PLUS DE 25 ANS D'EXPERIENCE" (registre pub/vitrine, date mal) a
#   ete remplace par une salutation dynamique selon l'heure (Bonjour/Bon apres-midi/Bonsoir/
#   Bonne nuit) + une question directe -- pattern etabli chez Claude/ChatGPT. Pas de prenom
#   en dur (Marvin reste distribuable a d'autres utilisateurs, aucun reglage "nom" n'existe
#   encore -- voir CLAUDE.md doctrine de distribution).
#   LivingAvatar.jsx retravaille : double halo bicolore (bleu+cyan, les 2 couleurs d'accent
#   deja dans le theme), coeur en dégradé 2 tons avec reflet au lieu d'un bleu plat, eclat
#   orbital qui tourne en continu (accelere quand Marvin reflechit), anneau au tracé plus
#   fin -- meme concept "vivant" (battement de coeur) deja etabli depuis v2.85, juste plus
#   de profondeur visuelle.
#   Teste en reel (Playwright + JS direct) : salutation confirmee dynamique ("Bonne nuit."
#   affiche a l'heure reelle du test) ; nouveaux elements SVG (eclat orbital, 2e halo,
#   3 degrades) confirmes presents dans le DOM ; 0 erreur console.
#
# v2.170 (titrage instantane des conversations + retroactif) : demande explicite (capture
#   d'ecran de la barre laterale, "rendre cette partie meilleure en s'inspirant des
#   meilleures pratiques des meilleurs AI du monde") -- une grande partie de la liste
#   n'etait jamais titree ("Nouvelle conversation" repete a l'infini, illisible).
#   Cause racine trouvee : l'auto-titrage n'existait qu'a UN seul des 3 points de
#   sauvegarde du message assistant (agent.py) -- si le tour etait interrompu avant
#   (flux abandonne, MAX_TOOL_STEPS, crash...) la conversation restait titree "Nouvelle
#   conversation" DEFINITIVEMENT, meme apres coup. Corrige a la racine : le titre est
#   desormais pose IMMEDIATEMENT a l'enregistrement du message UTILISATEUR (avant meme
#   que l'assistant reponde) -- independant de la reussite du tour, comme chez
#   Claude/ChatGPT (le titre apparait des l'envoi). Bloc post-hoc devenu redondant retire.
#   Backfill retroactif execute sur la base reelle (via l'API, pas d'acces DB direct) :
#   29 conversations existantes encore "Nouvelle conversation" retitrees a partir de
#   leur premier message utilisateur reel.
#   Teste en reel : appel direct a /api/chat, titre confirme pose (~2s apres l'envoi,
#   AVANT la fin de la reponse de l'assistant) -- preuve directe de l'independance vis-a-vis
#   de l'achevement du tour. Les 29 conversations retroactives verifiees avec des titres
#   coherents (ex. "fais un audit de securite de…", "mon wifi se deconnecte tout le…").
#
# v2.171 (recherche full-text + epinglage + titres intelligents) : suite directe de v2.170,
#   demande explicite ("comment pouvons-nous rendre cette sidebar meilleure ? regarde ce que
#   font les meilleurs AI et propose-moi" -> "fait les 3"). 3 lacunes trouvees en lisant le
#   code reel (pas supposees) compares a Claude/ChatGPT :
#   1. Recherche full-text (etait limitee au titre tronque a 6 mots) : nouvelle fonction
#      db.search_conversations() (JOIN messages, LIKE sur titre ET contenu) + endpoint
#      GET /api/conversations/search (DOIT etre declare AVANT /api/conversations/{cid} --
#      sinon FastAPI route "search" comme un cid litteral) + proxy Next.js
#      app/api/conversations/search/route.js + debounce cote frontend (app/page.js).
#   2. Epinglage (pattern Claude/ChatGPT) : colonne `pinned` ajoutee a la table conversations
#      (migration PRAGMA+ALTER, meme motif que le reste du fichier -- la table elle-meme est
#      historiquement creee cote JS, Python n'en a jamais eu la propriete complete du
#      schema). Nouvelle section "EPINGLEES" en haut de la sidebar, exclue des groupes
#      projet/date pour eviter les doublons visuels.
#   3. Titres intelligents en arriere-plan : la troncature immediate (v2.170) reste affichee
#      tout de suite, puis remplacee quelques secondes apres par un titre genere par un LLM
#      leger (_smart_title_upgrade, agent.py) -- passe par _ollama_generate (tools.py) donc
#      beneficie automatiquement du meme routage cloud/sensibilite que tout appel LLM
#      interne (v2.122), sans logique dupliquee. upgrade_conversation_title_silent() ne
#      touche PAS updated_at (sinon la conversation resauterait en haut de la liste une 2e
#      fois juste pour un changement de titre).
#   Teste en reel : recherche "wifi" a trouve un match sur le CONTENU d'un resultat
#   web_research stocke en base (pas le titre) -- preuve directe que le full-text fonctionne
#   au-dela du titre ; epinglage teste via l'API (conversation remonte en tete, pinned:1) ;
#   titre intelligent verifie de bout en bout ("peux tu me faire un script..." -> "Script
#   verification espace disque" en ~15s) ; recherche testee dans l'UI reelle (3 resultats
#   corrects affiches, dont le match content-only). Incident de session annexe (documente
#   par transparence) : le serveur Next.js dev avait un cache fige affichant une ERREUR DE
#   SYNTAXE PERIMEE (contenu different du fichier reel sur disque, confirme invalide via
#   babel) -- resolu en videant .next/ et redemarrant le process, pas un bug du code livre.
#
# v2.172 (fix file_create_pdf : schemas ASCII "boite" illisibles) : signale directement par
#   l'utilisateur sur une VRAIE conversation ("Schema reseau multi-VLANs" -> genere un PDF du
#   schema -> "je trouve la partie schema illisible est moche"). Diagnostique en rendant le
#   vrai PDF genere en image (pypdfium2, pas suppose) : chaque caractere de dessin de boite
#   (═ ║ ╔ ╗ ┌ ┐ ...) s'affichait en CARRE NOIR PLEIN -- les polices PDF standard de reportlab
#   (Courier/Helvetica, encodage WinAnsi/Latin-1) n'ont AUCUN glyphe pour le bloc Unicode
#   U+2500-257F, et meme corrige la largeur de page (Courier 9pt) aurait fait deborder/
#   s'envelopper les lignes de ~100 caracteres, cassant l'alignement de toute facon.
#   Corrige dans execute_file_create_pdf (tools.py) : les blocs de code detectes comme "art
#   ASCII boite" (regex sur la plage Unicode) sont desormais rendus en image PNG (police
#   Consolas -- couverture Unicode complete verifiee, presente sur Windows) via PIL, integres
#   au PDF en flowable Image mis a l'echelle de la largeur de page -- au lieu d'un Paragraph
#   texte. Les blocs de code NORMAUX (sans dessin de boite) gardent le rendu Courier existant,
#   inchange.
#   Teste en reel : meme contenu exact que le PDF defaillant original renvoye au tool via
#   /api/tools -> PDF rendu en image (pypdfium2) -> boites parfaitement lisibles et alignees ;
#   bloc de code JS normal juste en dessous confirme toujours rendu en texte Courier classique
#   (aucune regression sur le chemin existant).
#
# v2.173 (fix file_create_pdf : 2 bugs trouves EN REJOUANT la vraie conversation de l'utilisateur
#   apres coup) : l'utilisateur a continue la conversation "Schema reseau multi-VLANs" et
#   signale "il a eu un bug avant [de fournir le schema]". Rejoue via /api/history + le contenu
#   EXACT du tool call qui avait echoue -- pas une supposition, le vrai payload qui a plante.
#   1. LayoutError "too large on page" : le fix v2.172 ne mettait l'image a l'echelle QUE par
#      la LARGEUR (doc.width) -- un schema haut (15 PC + 2 serveurs + 4 switches, ~50 lignes)
#      depassait la hauteur utile de la page, et un flowable Image ne se scinde jamais sur 2
#      pages -> crash. Corrige : scale = min(1, largeur_dispo/iw, hauteur_dispo/ih), -12pt de
#      marge (padding par defaut du frame reportlab, 6pt x 2 cotes).
#   2. Tofu residuel sur les EMOJI dans le schema (✅❌🌍🔴🟢, statuts de matrice VLAN + icones
#      de noeud) : meme cause que v2.172 (Consolas ne les couvre pas non plus) mais pas
#      detecte au premier passage (le test initial n'avait pas d'emoji). Remplacement
#      caractere-par-caractere (jamais multi-caracteres, casserait l'alignement des colonnes/
#      bordures) : table figee pour les cas frequents (✅/❌ -> V/X, coincide avec la legende
#      deja presente dans le contenu original "V=autorise, X=bloque") + verification de
#      couverture de glyphe generique (font.getmask) en repli pour tout futur symbole non
#      anticipe -> remplace par un espace plutot qu'un tofu.
#   Testes en reel avec le contenu EXACT du tour qui avait plante dans la vraie conversation :
#   PDF genere sans erreur (18 pages), schema haut confirme tenir sur une seule page (rendu
#   image via pypdfium2), matrice VLAN confirmee lisible avec V/X propres -- coherent avec la
#   legende du document.
#
# v2.174 (identite document persistante + sommaire auto + en-tete/pied de page complets) :
#   demande explicite de l'utilisateur ("je veut qu'il demande automatiquement quel est le nom
#   de l'auteur, quel sera le haut de page, le bas de page, qu'il fasse un sommaire... inspire
#   toi sur le web, cherche et propose") -- recherche web menee (best practices document
#   generation), suivie d'un audit du code reel qui a revele que file_create_docx avait DEJA
#   en-tete/references/signature depuis des versions anterieures mais JAMAIS exposes dans
#   TOOLS_SPEC -- invisibles du LLM, donc jamais utilises. Le vrai trou n'etait pas la capacite
#   mais sa DECOUVRABILITE + l'absence totale de sommaire/identite persistante/pied de page libre.
#   1. `document_identity_set` (nouvel outil, 328e) : enregistre auteur/organisation/coordonnees/
#      logo/pied de page/confidentialite par defaut (db.get_setting("document_identity"), JSON).
#      Reutilise automatiquement en repli par file_create_pdf/file_create_docx si l'appelant ne
#      precise pas author/header/letterhead/footer_text pour CE document -- jamais ecrase.
#   2. Regle d'or #16 (agent.py) : avant de generer un document STRUCTURE/officiel sans identite
#      deja connue, Marvin pose UNE question groupee (auteur/organisation/sommaire) puis appelle
#      document_identity_set -- jamais pour un memo/export rapide (defaults silencieux). L'identite
#      deja connue est injectee dans le system prompt (meme pattern que les instructions de
#      Projects v2.142) pour que le modele SACHE qu'il n'a pas a redemander.
#   3. Sommaire auto : Word -- champ TOC natif (`w:updateFields` force la mise a jour a
#      l'ouverture, sinon Word affiche un placeholder jusqu'au clic droit). PDF -- reportlab
#      TableOfContents + doc.multiBuild() (2 passes, page reelle inconnue avant mise en page
#      complete) + sous-classe SimpleDocTemplate.afterFlowable() qui pose un signet PDF cliquable
#      par titre h1/h2 (bonus navigation, gratuit).
#   4. En-tete personnalise porte sur PDF (jusque-la reserve a Word) + pied de page en texte
#      libre + "Page X / Y" (pas juste "X") sur les deux formats via la recette reportlab
#      standard "NumberedCanvas" (le total de pages n'est connu qu'apres mise en page complete).
#   BUGS TROUVES ET CORRIGES EN TESTANT (pas supposes) : (a) "Index entries not resolved after
#   10 passes" -- le compteur de cles de signet (_toc_seq) n'etait jamais reinitialise entre les
#   passes de multiBuild(), donc les cles differaient a chaque passe et la convergence
#   n'aboutissait jamais -- corrige en resettant le compteur au debut de build().
#   Testes en reel de bout en bout : document_identity_set + PDF avec toc=true SANS auteur/en-tete
#   explicites -> repli identite confirme (org/email en en-tete, auteur sur la page de titre,
#   pied de page "texte · confidentialite" + "Page X / Y"), sommaire cliquable avec les bonnes
#   pages ; meme test sur Word -- converti en PDF via Word/COM reel (preuve que le fichier n'est
#   pas corrompu) -- TOC recalcule automatiquement a l'ouverture, identique au PDF. Reglages ->
#   Connexions verifie en reel (Playwright) : champs pre-remplis au chargement, sauvegarde
#   confirmee par relecture directe de l'API apres clic.
#
# v2.175 (📸 captures d'ecran persistees + analysees + documentation auto-generee) : demande
#   explicite ("je voudrais que marvin puisse ingurgiter beaucoup de screen dans la conversation
#   et de bien les analyse pour pouvoir faire des documentation sur mon travail"). Audit du
#   pipeline existant AVANT tout code : une image attachee au chat n'etait utilisee QUE pour CE
#   tour (agent.py extrayait le texte, jetait les images avant `db.create_message`) -- aucune
#   persistance, aucun moyen de les retrouver pour un tour ulterieur. Le modele vision local
#   (llava-phi3) a en plus ete pris en flagrant delit d'hallucination sur un benchmark reel
#   (image de test avec IP/code d'erreur/heure verifiables) : il a invente des enregistrements
#   DNS totalement fictifs. 3 modeles cloud installes (gemini-3-flash-preview, gemma4:31b,
#   qwen3.5:397b) ont extrait les 4 details EXACTS en ~6s -- preuve chiffree, l'utilisateur a
#   explicitement autorise le cloud pour ce pipeline precis apres avoir vu le resultat.
#   1. Persistance + analyse automatique (agent.py::_persist_and_analyze_screenshots) : chaque
#      image d'un message multimodal est sauvegardee sur disque (data/screenshots/<conv_id>/)
#      et analysee UNE FOIS (legende + texte relevé verbatim) via un nouveau pipeline vision
#      DEDIE (tools.py::_analyze_screenshot) — deliberement SEPARE de ocr_extract (qui reste
#      100% local par doctrine, v2.122, contenu potentiellement le plus sensible) : le cloud
#      n'est utilise ici QUE si cloud_enabled (opt-in existant) est actif, et local_only_lockdown
#      (Hyper securise) reste un plafond dur jamais contourne. Nouvelle table `screenshots`.
#   2. Support image ![legende](chemin) dans _parse_md_blocks -> embarque une VRAIE image dans
#      file_create_docx/file_create_pdf (jusqu'ici seuls texte/tableaux/code etaient supportes)
#      -- meme garde largeur+hauteur que le fix v2.173 pour eviter un LayoutError PDF.
#   3. 2 nouveaux outils (330e/331e) : screenshot_list (liste ce qui est deja analyse pour la
#      conversation courante) et doc_generate_from_screenshots (compile toutes les captures en
#      un Word/PDF structure — une section par capture, image + legende + texte releve — avec
#      sommaire auto v2.174). conversation_id injecte automatiquement par agent.py (meme
#      pattern que long_task_start v2.145) — jamais devine par le modele (regle d'or #7).
#   Teste en reel de bout en bout : 2 captures synthetiques (jamais le vrai bureau de
#   l'utilisateur — action bloquee par le classifieur, a raison, contournee avec une image
#   generee) envoyees via /api/chat -> "screenshots_saved: 2" confirme, legende ET texte releve
#   100% exacts (serveur/IP/commande PowerShell/statut) -> doc_generate_from_screenshots (docx
#   ET pdf) -> converti en PDF via Word/COM reel -> images bien integrees, sommaire correct,
#   pagination correcte. Donnees de test nettoyees apres verification.
#
# v2.176 (📦 kit de deploiement Windows Server pour un poste boutique) : demande explicite
#   ("je vais telecharger le dossier marvin pour l'installer sur un windows server prevu pour
#   la boutique... que tout les dependances soit contenu... qu'un fichier d'installation
#   procedural puisse etre suivi"). Audit des scripts existants (INSTALLER-NOUVEAU-PC.bat,
#   start.bat, VERIFIER-INSTALLATION.bat, deja solides) AVANT tout changement : 4 vrais risques
#   trouves specifiques a une cible Windows Server (pas juste un PC client) -- winget souvent
#   absent par defaut sur Server, acces internet incertain en arriere-boutique, next dev (pas
#   next build+start) inadapte a un serveur sans surveillance, rien ne relance Marvin apres un
#   reboot. Questions posees a l'utilisateur avant de coder (AskUserQuestion) : acces internet
#   confirme solide -> pas besoin du kit 100% hors-ligne envisage initialement ; droits admin
#   confirmes -> installation classique au niveau systeme.
#   1. INSTALLER-NOUVEAU-PC.bat : detecte l'absence de winget une fois, et pour Node.js resout
#      dynamiquement la derniere version LTS via l'API JSON officielle nodejs.org/dist/index.json
#      (jamais un numero de version fige en dur qui deviendrait faux avec le temps) puis
#      telecharge+installe silencieusement ; meme principe pour Ollama (URL stable
#      ollama.com/download/OllamaSetup.exe) ; pour Python (pas d'equivalent JSON simple),
#      ouverture de la page officielle plutot que de deviner une URL de version precise.
#   2. START-PRODUCTION.bat (nouveau) : construit le frontend une fois (`npm run build`, requiert
#      `next start -H 0.0.0.0` ajoute a package.json pour l'ecoute reseau) puis le sert en mode
#      PRODUCTION -- delibrement separe de start.bat (mode developpement, reste inchange pour les
#      machines de dev). Argument "rebuild" pour reconstruire apres une mise a jour du code.
#   3. INSTALLER-DEMARRAGE-AUTO.bat (nouveau) : enregistre une tache planifiee Windows (`schtasks`,
#      declencheur au demarrage, compte SYSTEM) pour que Marvin reparte seul apres un reboot/une
#      coupure -- important pour un serveur de boutique sans surveillance permanente. Contrepartie
#      documentee (pas de session de bureau interactive sous SYSTEM -> notifications/presse-papiers
#      indisponibles dans ce mode) plutot que laissee decouvrir en silence.
#   4. INSTALLATION.md (nouveau) : procedure numerotee en francais, une commande par etape avec le
#      resultat attendu, incluant l'ouverture du pare-feu Windows pour l'acces depuis le reseau de
#      la boutique (etape absente des scripts existants, oubliee jusqu'ici).
#   Teste en reel sur cette machine (le seul test possible sans un vrai Windows Server sous la
#   main) : `npm run build` execute reellement sur le code actuel -> 51 routes compilees sans
#   erreur ; `npm run start` demarre et repond HTTP 200 + `/api/status` correct ; chemin winget-
#   present verifie intact (aucune regression sur le flux existant, ce PC a winget) ; etat du
#   serveur de dev restaure a l'identique apres le test (aucun residu).
#
# v2.177 (🧹 paquet de deploiement propre — sans donnees personnelles) : remarque directe de
#   l'utilisateur juste apres v2.176 ("pense que nouvelle installations vide la memoire de mes
#   souvenir clean") -- signal a prendre au serieux : "je vais telecharger le dossier marvin"
#   (copie brute du dossier, pas un `git clone`) aurait embarque `data/` (conversations,
#   memoires, captures d'ecran v2.175, sauvegardes, jeton eleve) ET `backend/data/` (cle de
#   compte de service Google) tel quel sur le serveur boutique -- ces dossiers sont exclus de
#   GIT (.gitignore) mais RIEN n'empeche un copier-coller brut de les inclure.
#   Nouveau `PREPARER-PAQUET-BOUTIQUE.bat` : robocopy vers un dossier voisin en excluant
#   `data/`, `backend/data/`, `.venv`, `node_modules`, `.next`, `.git`, `.env.local`, et les
#   fichiers de debug/scratch deja listes dans .gitignore (`*.log`, `last-event.json`,
#   `_mining_ui.png`...) -- verification explicite affichee a la fin (aucun `data/` present).
#   `INSTALLATION.md` mis a jour : etape 0 recommande desormais ce script en premier ; l'ancienne
#   phrase "data/ DOIT etre copie" (ambigue, ecrite pour le cas migration) reformulee pour
#   distinguer clairement nouvelle installation (par defaut, ne PAS copier data/) de migration
#   (cas explicite et volontaire, a part).
#   Bug reel trouve EN TESTANT le script (pas suppose) : toutes les references `!DEST!` du
#   script se retrouvaient traitees comme du texte LITTERAL par cmd.exe (un dossier nomme
#   `!DEST!` etait cree au lieu du chemin resolu) -- diagnostique par isolation (la delayed
#   expansion seule fonctionne en test isole ; recherche caractere par caractere a trouve un
#   seul mot accentue "competences" reste dans le fichier, malgre la convention ASCII-only deja
#   respectee partout ailleurs dans les .bat du projet precisement pour cette classe de bug
#   `chcp 65001`/encodage). Corrige (ASCII), reverifie en reel (dossier bien nomme cette fois,
#   data/backend-data/.env.local bien absents du paquet).
#
# v2.178 (☁️ Mode Cloud Total scripte pour serveur boutique sans GPU) : demande explicite
#   ("le serveur qui va accueillir marvin n'a pas de gpu donc faudrait faire un mode full
#   cloud sans blocage de securite... on n'a pas le choix"). Avant de coder, question posee
#   (AskUserQuestion) pour lever une ambiguite critique sur "sans blocage de securite" -- deux
#   garde-fous COMPLETEMENT differents dans Marvin portent ce nom en usage courant : (1) le
#   routage cloud/local par SENSIBILITE (emails/SSH/mdp/factures -> local par defaut) et (2) le
#   garde-fou SYSTEME de security.py (formatage disque, rm -rf...). Confirme : seulement (1),
#   jamais (2) -- coherent avec la doctrine du projet (jamais affaiblir security.py, deja
#   documente a plusieurs reprises). 2e question posee : l'OCR/vision generaliste doit-il aussi
#   basculer au cloud sur cette machine ? Reponse : non, reste local par defaut (contenu
#   potentiellement sensible, factures clients) -- seul le pipeline captures->documentation
#   v2.175 (deja opt-in via cloud_enabled) en beneficie.
#   Trouvaille en auditant AVANT de coder : le mode demande EXISTE DEJA integralement --
#   le preset "Ultra debride" (v2.121, app/settings/page.jsx::applyPreset) fait deja
#   EXACTEMENT ca (cloud_enabled=true + cloud_overrides sur les 3 profils + ultra_unrestricted=
#   true + local_only_lockdown=false), avec le garde systeme explicitement documente comme
#   jamais touche des sa conception. Aucune nouvelle logique de routage necessaire.
#   Seul vrai manque : ce preset necessite un clic dans l'UI + une boite de confirmation
#   navigateur (window.confirm) -- peu pratique pour un serveur deploye sans interaction UI
#   prevue. Nouveau `CONFIGURER-CLOUD-TOTAL.bat` : applique la MEME configuration directement
#   via l'API (/api/settings/*), avec la meme logique de choix du meilleur modele cloud
#   installe (deepseek > glm > kimi > premier disponible) que l'UI.
#   Teste PARTIELLEMENT en reel, par prudence delibérée : le classifieur de permissions a
#   bloque une tentative de tester meme la SYNTAXE des appels PUT contre une URL FICTIVE,
#   reconnaissant a raison le meme mecanisme qu'une vraie activation d'ultra_unrestricted sur
#   la configuration reelle de cette machine (deja bloque une fois en v2.121 pour la meme
#   raison) -- respecte sans contournement. Verifie a la place, en isolation et sans effet de
#   bord : la capture de sortie PowerShell via for/f usebackq+backticks (testee et confirmee
#   fonctionnelle), et la resolution du meilleur modele cloud installe sur cette machine
#   (deepseek-v4-flash:cloud correctement selectionne parmi 7 modeles cloud installes).
#
# v2.179 (🔮 selection de modele cloud resiliente au retrait — plus jamais un tag fige) :
#   preuve concrete apportee par l'utilisateur (capture d'ecran du compte Ollama Cloud) : 2
#   modeles recommandes DANS CETTE SESSION (gemini-3-flash-preview pour la vision v2.175,
#   qwen3-coder:480b pour le routage code v2.141) seront retires par le fournisseur dans 2
#   jours. Confirme que coder un nom de modele exact en dur (meme "juste" recommande, pas
#   la ligne officielle de securite) est fragile par nature avec des modeles cloud qui
#   tournent -- exactement la classe de probleme que la regle d'or #7 (jamais halluciner un
#   identifiant technique non verifie) anticipait deja pour d'autres cas.
#   `cloud_routing.py` : nouveau `pick_best_cloud_model(need)` + `list_vision_candidates()` --
#   resolvent le meilleur modele EN DIRECT sur `ollama_models` (jamais une liste figee), par
#   FAMILLE (prefixe : deepseek/glm/kimi/nemotron en general, gemini/gemma/qwen3.5 en vision,
#   tout modele contenant "coder" en code) plutot que par tag exact -- survit automatiquement
#   a un retrait/renommage futur sans modification de code, puisque `list_installed_cloud_models()`
#   reflete toujours ce qui est REELLEMENT installe au moment de l'appel.
#   Nouvel endpoint `GET /api/cloud/best-model?need=...` : point d'entree UNIQUE partage par
#   `tools.py::_analyze_screenshot` (vision), `agent.py::run_agent` (routage par tache, code),
#   `app/settings/page.jsx::applyPreset` (UI) ET `CONFIGURER-CLOUD-TOTAL.bat` (deploiement
#   serveur boutique v2.178) -- fini les 3 implementations dupliquees et desynchronisees
#   trouvees en auditant (une seule cote UI ne detectait meme pas correctement les tags
#   `-cloud` vs `:cloud`, bug de la meme famille que celui deja corrige en v2.141 ailleurs).
#   Reglage `cloud_task_overrides` devenu obsolete (plus aucun consommateur) -- nettoye sur
#   cette machine (pointait vers qwen3-coder:480b-cloud, le modele qui va retirer).
#   `CONFIGURER-CLOUD-TOTAL.bat` durci sur un point separe, demande explicitement par
#   l'utilisateur ("differencie bien l'installation sur le serveur et l'installation sur
#   n'importe quel autre windows comme le mien") : detection GPU (Get-CimInstance
#   Win32_VideoController) avec confirmation tapee obligatoire si une VRAIE carte graphique
#   est trouvee -- empeche d'appliquer par erreur ce mode "tout cloud, sensibilite ignoree"
#   sur un poste de travail normal qui a deja un GPU et fonctionne bien en local.
#   Teste en reel : endpoint /api/cloud/best-model verifie sur les 3 besoins (general ->
#   deepseek-v4-flash:cloud, vision -> gemini-3-flash-preview:cloud, code -> qwen3-coder:480b-cloud
#   -- tous deux encore installes AUJOURD'HUI, la resolution bascule automatiquement sur le
#   suivant de la famille des que le fournisseur les retire reellement, sans intervention).
#   Detection GPU verifiee en isolation (carte integree Intel detectee correctement comme
#   "un GPU present" sur cette machine de developpement). Page Reglages > Modele IA rechargee
#   en reel apres redemarrage backend, 0 erreur console.
#
# v2.180 (📡 acces LAN automatise + apprentissage passif des capacites modeles) : 2 demandes
#   dans le meme message. (1) "marvin doit etre accessible sur le lan de la boutique...
#   incorporer cela dans les reglages de la version installable" -- l'ouverture du pare-feu
#   (New-NetFirewallRule, ports 3000/8005) etait jusqu'ici une commande PowerShell a copier-
#   coller a la main dans INSTALLATION.md. Deplacee dans INSTALLER-DEMARRAGE-AUTO.bat (deja
#   admin-only), idempotente (supprime puis recree les regles -- relancer plusieurs fois ne
#   cree pas de doublons). INSTALLATION.md restructure (etapes 4/4bis fusionnees en une seule
#   section coherente "acces LAN + demarrage auto").
#   (2) "que les meilleurs models cloud soit utiliser automatiquement selon le contexte...
#   que marvin connaisse tous les modeles et leur utilite de facon autonome" -- rejete
#   deliberement le sondage proactif (tester chaque modele installe a l'avance couterait du
#   quota cloud reel pour zero benefice utilisateur, l'abonnement Ollama Cloud a un plafond de
#   session visible cote utilisateur). A la place : apprentissage PASSIF depuis les VRAIS
#   appels -- `cloud_routing.py::record_model_capability(model, need, ok)` memorise le
#   resultat REEL de chaque appel vision (succes ou echec 4xx = incapacite constatee ; un
#   timeout/5xx transitoire n'est PAS memorise comme un echec de capacite, pour ne pas exclure
#   a tort un modele valide). `pick_best_cloud_model()`/`list_vision_candidates()` consultent
#   cet historique appris : exclut les modeles constates incapables, fait remonter en tete
#   ceux constates capables (experience reelle prioritaire sur la simple heuristique de
#   famille v2.179). Meme doctrine que l'auto-reparation des competences (skills.py) :
#   apprendre de l'echec/succes reel, jamais deviner ni sonder a l'avance.
#   Teste en reel de bout en bout : ouverture pare-feu testee en isolation (erreur "Acces
#   refuse" attendue en non-admin, confirme la syntaxe correcte -- gerable proprement par le
#   script) ; pipeline vision declenche pour de vrai via /api/chat avec une image de test ->
#   gemini-3-flash-preview:cloud reellement appele, a reussi, capacite "vision: ok=true"
#   effectivement enregistree en base et relue via /api/cloud/best-model. Donnees de test
#   nettoyees (conversation + fichiers), capacite apprise laissee en place (donnee reelle utile).
#
# v2.181 (🩹 fix INSTALLER-NOUVEAU-PC.bat — plantage net sur Windows Server a l'etape Node.js) :
#   signale directement par l'utilisateur ("le script install-nouveau-pc ne fonctionne pas sur
#   windows server... la fenetre se ferme quand ca arrive sur node js"). D'abord une fausse piste
#   ecartee sur preuve : le premier message d'erreur colle par l'utilisateur (erreurs de parsing
#   PowerShell sur "@echo off"/"&"/parentheses) venait en realite d'avoir ouvert/execute le
#   fichier .bat DANS POWERSHELL ISE (qui interprete le contenu comme du code PowerShell, pas du
#   batch) -- pas un bug du script. Documente dans INSTALLATION.md (jamais ouvrir un .bat dans
#   ISE ni coller son contenu dans une console PowerShell).
#   Le VRAI bug, confirme par la description precise du symptome (fenetre qui se ferme NETTEMENT,
#   sans message, pile a l'etape Node.js) : la ligne PowerShell -Command de resolution dynamique
#   de la version Node LTS (v2.176) utilisait des guillemets doubles ECHAPPES imbriques
#   (\"..\") pour l'interpolation de chaine PowerShell -- ce motif fait planter net le parseur
#   de cmd.exe sur certaines installations Windows Server (jamais reproduit sur cette machine de
#   developpement, differences de version cmd.exe/console host). Corrige en ecrivant le script
#   PowerShell dans un VRAI fichier .ps1 temporaire (via une serie d'`echo >>`, chaque `(` `)` `|`
#   correctement echappes pour rester a l'interieur du bloc batch `else ( ... )`) puis en
#   l'executant via `-File` -- elimine entierement le risque de quoting cmd.exe/PowerShell
#   imbrique, plus jamais de guillemets echappes nulle part dans ce fichier.
#   Bug ANNEXE trouve en corrigeant (pas suppose) : le premier correctif capturait
#   `!ERRORLEVEL!` APRES un `del` intercalaire, qui ecrasait silencieusement le code de sortie
#   reel du `powershell` par celui du `del` (toujours 0) -- le chemin d'erreur n'aurait donc
#   jamais pu se declencher. Corrige en capturant `!ERRORLEVEL!` dans une variable JUSTE apres
#   l'appel PowerShell, avant tout autre commande.
#   Teste en reel de bout en bout (isole du script complet, meme bloc exact) : cas de succes ->
#   version LTS resolue dynamiquement (v24.18.0 au moment du test), MSI reellement telecharge
#   (32,8 Mo) ; cas d'echec force (domaine invalide) -> code d'erreur correctement capture et
#   propage, message clair affiche -- les deux chemins verifies fonctionnels, plus de fermeture
#   brutale de la fenetre.
# v2.182 -- INSTALLER-NOUVEAU-PC.bat : reparation automatique d'un pip manquant.
#   Suite directe du v2.181 : l'utilisateur a confirme (via `python -m pip --version` correctement
#   invoque depuis l'invite, pas une erreur de contexte REPL comme sa premiere tentative) que pip
#   est reellement absent de l'installation Python 3.14.6 de son Windows Server ("No module named
#   pip"). L'etape [1/9] Python du script ne verifiait jusqu'ici QUE la presence de l'executable
#   `python`, jamais celle de pip -- laissant l'etape [6/9] (creation du venv + pip install) planter
#   plus loin avec une erreur moins claire.
#   Fix : verification en lecture seule (`python -m pip --version`, ne modifie rien) juste apres la
#   detection de Python ; si absent, reparation via `python -m ensurepip --upgrade` (methode
#   officielle, integree a la stdlib, ne telecharge rien depuis internet) ; erreur claire si meme
#   ensurepip echoue (repli : reinstaller Python en cochant "pip" dans les composants optionnels).
#   Contrainte explicite de l'utilisateur respectee : AUCUNE commande de reparation (ensurepip)
#   executee sur cette machine de developpement (son pip fonctionne deja) -- seule la verification
#   en LECTURE SEULE a ete testee ici (`python -m pip --version`, confirme pip 26.1.2 present, zero
#   modification). La logique de branchement (pip present / absent-repare / absent-ensurepip-echoue)
#   testee en isolation via un script batch jetable simulant les 3 codes de sortie, hors de toute
#   invocation Python reelle. Bug cosmetique trouve et corrige pendant ce test isole : un `!` isole
#   dans `[!]` a l'interieur d'un bloc parenthese sous `enabledelayedexpansion` est silencieusement
#   avale par le parseur cmd.exe (affiche `[]` au lieu de `[!]`) -- remplace par `[ATTENTION]`, deja
#   la convention etablie ailleurs dans ce meme fichier, qui n'a pas ce probleme.
# v2.183 -- Audit d'une vraie conversation (echec total de generation de logo) : 4 correctifs.
#   Demande explicite de l'utilisateur (« regarde la derniere conversation ... corrige tout cela
#   et rend marvin meilleur »). Rejoue la conversation "Message de salutation" via /api/conversations
#   au lieu de deviner -- a revele 7 tentatives consecutives echouees de generer un logo via
#   PowerShell/System.Drawing, un PDF avec 2 pages quasi vides, et le scroll du chat qui se
#   faisait kidnapper pendant le streaming.
#   1. BUG RACINE trouve (tools.py::execute_pc_run_command) : une commande qui invoque DEJA
#      explicitement `powershell -Command "..."` et contient un cmdlet (New-Object...) etait
#      auto-routee vers execute_pc_run_powershell, qui l'encode ENTIEREMENT (guillemets inclus)
#      comme -EncodedCommand -- le powershell EXTERIEUR interpole alors les `$variable` a
#      l'interieur de la chaine entre guillemets AVANT de lancer le powershell imbrique voulu,
#      les videant silencieusement (`$bmp = New-Object ...` -> ` = New-Object ...`). Exactement
#      le symptome observe sur les 7 tentatives. Corrige (_PWSH_ALREADY_INVOKED_RE) : une commande
#      qui invoque deja powershell.exe/pwsh n'est plus re-emballee, lancee directement (cmd.exe
#      n'interprete jamais `$`). Verifie en reel : `powershell -Command "$x='hello';Write-Output $x"`
#      renvoie maintenant "hello" (renvoyait vide/erreur avant).
#   2. Marvin n'avait AUCUN outil de generation d'image -- seul recours du LLM face a "invente un
#      logo" : ecrire du System.Drawing a la main (fragile, cause du bug ci-dessus). Nouveau
#      `local_image.py` (stabilityai/sd-turbo, reutilise la detection GPU dynamique de
#      local_video.py) + outils `logo_generate`/`logo_list` (table `logos`, reutilisable sans
#      regenerer). Teste en reel : logo genere en 49s (RTX 2060), integre avec succes dans l'en-tete
#      d'un PDF (deja supporte par `header.logo`, aucune plomberie supplementaire necessaire).
#   3. PDF (`file_create_pdf`) : (a) le bloc titre restait colle en haut avec ~70% de page blanche
#      en dessous quand `toc=True` force une page dediee (signale : "une ou deux page assez vide")
#      -- corrige par un espaceur qui centre visuellement le bloc. (b) Les emoji dans les titres
#      h1/h2 (aucun glyphe dans les polices PDF standard) se rendaient en carres noirs -- un emoji
#      multi-codepoint (🖥️ = DESKTOP COMPUTER + VARIATION SELECTOR-16) produisait DEUX carres colles
#      ("■■ Inventaire des Serveurs" dans le sommaire, repere exactement dans le PDF audite).
#      Corrige (_EMOJI_STRIP_RE dans _md_inline_to_rl) : retire les emoji des titres/paragraphes
#      PDF plutot que de les substituer (pure decoration, pas de substitut 1-pour-1 satisfaisant).
#   4. Chat (ChatContainer.jsx) : l'effet d'auto-scroll forcait `scrollTop=scrollHeight` a CHAQUE
#      token pendant le streaming, kidnappant le scroll des que l'utilisateur remontait lire un
#      passage (demande explicite : "je doit pouvoir scroll... meme quand marvin est en train de
#      generer sa reponse"). Corrige (stickToBottomRef, seuil 80px) : ne force le scroll que si
#      l'utilisateur etait deja "colle" au bas -- un nouvel envoi recolle toujours. Verifie en reel
#      (Playwright) : capture d'ecran prise EN PLEIN STREAMING ("Marvin ecrit... 6s" visible) montre
#      la vue restee scrollee sur un ancien message, le contenu en cours de generation hors champ.
#   5. Bonus (demande explicite "laisse le choix du format... et pouvoir le changer meme une fois
#      genere") : nouvel outil `document_convert_format` (docx<->pdf, sans regenerer le contenu --
#      docx->pdf reutilise Word/docx2pdf deja existant, pdf->docx via la nouvelle dependance
#      pdf2docx) + bouton "⇄ En .pdf/.docx" sur la carte de fichier genere dans le chat. Teste en
#      reel dans les deux sens (PDF avec logo -> Word, image + texte preserves ; Word -> PDF).
# v2.184 -- Journal des VRAIS bugs (exceptions + traceback complet), demande explicitement avant
#   une periode d'usage intensif sans nouvelle fonctionnalite (« tout probleme doit etre logue
#   pour pouvoir le debugger »). Ce qui existait deja (audit.jsonl, tool_executions) trace QUI a
#   fait QUOI et le taux de succes/echec, mais AUCUN des deux ne garde la stack trace Python --
#   juste str(exception). Nouveau `backend/bug_log.py` (data/bug_log.jsonl, filtre les secrets
#   comme audit.py) : capture le traceback COMPLET a 3 points -- (1) les 2 endroits ou la boucle
#   agent execute un outil (`except Exception as ex` ne gardait que str(ex)), (2) les 2 endpoints
#   /api/tools (UI + MCP) qui levaient une HTTPException sans rien logger, (3) un handler
#   d'exception GLOBAL FastAPI (@app.exception_handler(Exception)) qui attrape tout crash qui
#   s'echapperait d'une route sans passer par les 2 points precedents -- sans intercepter les
#   HTTPException normales (deja gerees par Starlette). Nouvel outil chat-usable `bug_log_list`
#   pour consulter ces bugs plus tard (moi ou l'utilisateur), distinct de `pc_tool_reliability`
#   (taux d'echec agrege) -- celui-ci donne le detail exploitable de chaque crash individuel.
#   Teste en reel : exception forcee (division par zero) -> capturee avec traceback complet,
#   argument sensible correctement filtre ("***"), relue via bug_log_list en conditions reelles
#   par l'API /api/tools ; handler global confirme enregistre sur l'app FastAPI. Entree de test
#   nettoyee du journal apres verification (data/bug_log.jsonl vide au demarrage de l'usage reel).
# v2.185 -- « donne-moi la commande » executait la commande au lieu de juste l'ecrire.
#   Signale directement par l'utilisateur (« quand je demande une commande marvin me la donne
#   mais tente de se connecter en ssh et/ou de la faire sur le pc »). Confirme en rejouant une
#   vraie conversation ("Installer Hyper-V et activer WSL 2") : sur "la commande...pour que
#   hyper v soit active toujours", Marvin a appele ssh_list PUIS reellement execute la commande
#   localement (pc_run_powershell, escalade jusqu'a pc_run_elevated) -- alors que meme le tour
#   suivant, ou l'utilisateur precisait explicitement "et ne lance rien", Marvin a quand meme
#   appele ssh_list. La regle d'or #14 existante couvrait deja "ecrire != executer" pour un OS
#   different/une machine distante, mais pas ce cas precis (meme OS, machine locale, aucun verbe
#   d'execution) -- le prompt seul n'a pas suffi (plafond deja documente ailleurs cette session).
#   Fix en 2 couches : (1) regle #14 etendue avec le cas precis signale, verifie en reel sur les
#   2 formulations exactes de la conversation -- le raisonnement visible du modele cite desormais
#   explicitement "rule #14" et repond en texte, 0 appel d'outil sur les 2 cas. (2) Filet
#   deterministe complementaire (_wants_command_text_only) : si le dernier message correspond a
#   "donne-moi/quelle est la commande" SANS verbe d'execution, pc_run_command/pc_run_powershell/
#   pc_run_elevated/ssh_exec*/ssh_write_and_run/ssh_list/ssh_server_info sont bloques ce tour --
#   meme mecanisme deja eprouve que le blocage d'outil explicite (regle #6). Piege trouve ET
#   corrige en testant sur le texte REEL de la conversation : "...et ne lance rien" contient
#   "lance" et se lisait comme un verbe d'AUTORISATION -- l'exact inverse de l'intention -- corrige
#   avec une detection de negation dediee. scripts/smoke_test_chat.py 5/5, smoke_test_pages.py 34/34.
# v2.186 -- Selecteur de voix restaure dans la barre de saisie (visible en permanence).
#   Signale directement (« je ne vois plus l'option pour changer la voix de marvin »). Trouve en
#   auditant ChatContainer.jsx : le <select> de choix de voix existe toujours, mais il n'etait
#   rendu QUE dans le bandeau "Mode vocal actif" (mains-libres) -- donc invisible des que ce mode
#   n'est pas active, ce qui est le cas la plupart du temps (l'utilisateur utilise surtout le
#   bouton 🔊 "Ecouter la reponse" par message, pas le mode continu). Corrige en ajoutant un bouton
#   "▾" persistant dans ChatInput.jsx, juste a cote du bouton haut-parleur -- meme pattern deja
#   eprouve que le choix du micro juste au-dessus (menu deroulant, fermeture Echap/clic exterieur).
#   voiceList est deja charge sans condition au montage (useVoice.js), aucun changement backend
#   necessaire. Teste en reel (Playwright) : bouton trouve et fonctionnel, menu affiche les 7
#   voix installees, selection d'une voix (Sylvie) persistee dans localStorage ET confirmee apres
#   rechargement complet de la page. scripts/smoke_test_pages.py 34/34.
# v2.187 -- Fix : plusieurs voix TTS se melangeaient (lecture concurrente).
#   Signale directement (« j'ai l'impression que parfois j'entends plusieurs voix se
#   melanger »), juste apres l'ajout du selecteur de voix v2.186. Cause racine trouvee dans
#   lib/hooks/useVoice.js::runPlayer() : deux appels rapproches a speak()/stopSpeaking() (ex.
#   cliquer "Ecouter" deux fois vite, ou sur deux messages differents) pouvaient laisser DEUX
#   boucles de lecture actives simultanement. stopSpeaking() coupe l'audio en cours via
#   `audio.src = ''`, ce qui declenche un `onerror` ASYNCHRONE -- le temps qu'il arrive, la
#   NOUVELLE boucle a deja remis `playingRef.current` a true et rempli la file PARTAGEE
#   (queueRef). L'ANCIENNE boucle, en reprenant apres son await, voit alors `playingRef.current`
#   de nouveau a true et continue a consommer/jouer un morceau de la NOUVELLE file en parallele
#   de la nouvelle boucle -> deux <audio> lus en meme temps (voix qui se chevauchent).
#   Trouvaille frappante : un garde-fou de generation (`speakSeqRef`) existait DEJA dans le
#   code (commentaire "incremente a chaque speak -> annule les precedents") mais n'etait
#   JAMAIS incremente ni verifie nulle part -- implementation a moitie faite. Cable pour de
#   vrai : chaque `runPlayer()` capture son numero de generation au demarrage et abandonne
#   immediatement, sans toucher aux refs partagees, des que ce numero ne correspond plus a la
#   generation courante (bumpee par `stopSpeaking()`).
#   Teste en reel (Playwright, pas suppose) : instrumentation de `window.Audio` pour compter
#   les lectures concurrentes -- sur le code D'ORIGINE (git stash), 3 clics rapproches sur
#   "Ecouter" produisent bien un pic a 3 audios joues SIMULTANEMENT (reproduit le bug a
#   l'identique) ; avec le correctif restaure, le meme scenario exact ne depasse jamais 1 audio
#   concurrent. Verifie aussi /api/voice/speak et /api/voice/voices en reel (200, MP3 valide),
#   bug_log_list vide (aucun crash serveur cote pipeline vocal). scripts/smoke_test_pages.py 34/34.
# v2.188 -- Consolidation structurelle : version publique centralisee dans app_version.py,
#   URL FastAPI partagee cote frontend, controle statique des invariants d'architecture et
#   documentation remise au niveau du produit reel. Aucun outil ni comportement supprime.
# v2.189 -- Socle de validation reproductible : orchestrateur quick/build/live sans second
#   processus Qdrant, controle ABI Node, smoke test HTTP, preflight de demarrage et arret
#   controle des services. Extraction pilote des routes Doctor vers api/doctor.py avec
#   verification automatique du montage des routeurs avant le decoupage par domaines.
# v2.190 -- Garde-fous d'intention avant le LLM : reponses de quiz, demandes sans outil et
#   questionnaires texte restent conversationnels. Matching des competences ancre dans les
#   mots/declencheurs reels et contexte precedent reserve aux follow-ups explicites.
# v2.191 -- Extraction des routes conversations vers api/conversations.py, avec contrat HTTP
#   de reconstruction des messages et controle automatique du montage du routeur.
# v2.192 -- Extraction des CRUD projets, taches et notes dans trois routeurs dedies ;
#   contrats GET en lecture seule et listes Pydantic avec default_factory.
# v2.193 -- Extraction des memoires, parametres et sauvegardes ; confirmation de restauration
#   preservee hors du registre d'outils et contrats live strictement en lecture seule.
# v2.194 -- Extraction de l'historique d'execution, des statistiques de fiabilite et des
#   templates d'outils ; contrats live sans creation ni suppression de donnees.
# v2.195 -- Extraction des domaines facturation, documentation technique et operations ;
#   routes de decision conservees avec leurs validations et contrats live en lecture seule.
# v2.196 -- Adaptateurs HTTP Winget, Pantheon, Catharsis et Codex extraits ; confirmations
#   issues des interfaces conservees a l'identique sur toutes les actions mutantes.
# v2.197 -- Diagnostic de routage, acces reseau mobile et routes documents/RAG extraits ;
#   racine data calculee depuis le backend pour preserver les emplacements historiques.
# v2.198 -- Routes d'evenements et abonnements iCal extraites ; les trois modes de connexion
#   agenda restent portes par les outils existants sans changement de priorite.
# v2.199 -- Execution parallele multi-agents extraite avec contrat SSE preserve et execution
#   vide testable sans declencher le moindre outil.
# v2.200 -- CRUD et moteur de workflows extraits avec templating type, conditions, retries,
#   continue-on-error et traces d'execution preserves.
# v2.201 -- Transcription Whisper et synthese Edge-TTS extraites ; prechauffage reconnecte au
#   lifespan pour conserver la latence faible du premier enregistrement.
# v2.202 -- Telegram, apprentissage, auto-configuration et audit extraits ; lecture Telegram
#   continue de masquer le token et aucun test sortant n'est lance par les contrats.
# v2.203 -- API complete des competences Markdown extraite : generation, ressources, versions,
#   statistiques, suggestions et consolidation, sans rendre le contenu executable.
# v2.204 -- Recherche semantique/unifiee, chemins PC, apercus, pieces jointes et images du chat
#   extraits dans un domaine contenu unique, avec les limites de taille historiques.
# v2.205 -- Identifiants masques et flux OAuth Google/Microsoft extraits ; compte de service,
#   OAuth utilisateur et iCal restent tous disponibles sans changement de priorite.
# v2.209 -- Saisie multi-expéditeurs de l'automatisation email corrigée côté interface.
# v2.210 -- Orchestrateur email multiboîte : OAuth2 Gmail/XOAUTH2 par compte, profils
#   indépendants, simulation sans effet de bord, garde-fous anti-boucle, threading RFC,
#   planificateur explicitement confirmé et envoi différé annulable.
# v2.211 -- Council v2 et corrections fondees sur les conversations des 13-15 juillet :
#   cinq familles Ollama Cloud distinctes, cinq roles independants, critique anonymisee,
#   arbitrage inverse et provenance exacte sans repli local maquille. « Mode Council » force
#   desormais l'appel reel. Overrides cloud valides en direct, historique sensible pris en
#   compte, sorties/suppressions toujours confirmees meme en Expert, compatibilite command->
#   script pour PowerShell et enregistrement d'une cible SSH sans secret depuis le chat.
# v2.212 -- Marvin Cortex : contrat de mission structure a six axes transmis hors du texte,
#   routage explicable et retrocompatible, controle local par message, verification/Council
#   sur desaccord, graphe SSE, provenance des preuves et recettes persistantes mesurees.
# v2.208 -- Endpoint de santé et cache Ollama isolés dans api/health.py.
# v2.207 -- Domaine SSH isolé dans api/ssh.py (CRUD, SSE, WebSocket et SFTP).
# v2.206 -- Calcul des plannings centralise dans scheduling.py, routes Cron et monitoring SSE
#   extraites ; le worker et l'API partagent desormais strictement le meme calcul.

app = FastAPI(title="Marvin — Assistance Informatique", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8005", "http://127.0.0.1:8005"],
    # Autorise aussi l'accès depuis le réseau local (téléphone) : IP privées en :3000
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(doctor_router)
app.include_router(cortex_router)
app.include_router(forge_router)
app.include_router(evolution_router)
app.include_router(missions_router)
app.include_router(model_market_router)
app.include_router(knowledge_router)
app.include_router(conversations_router)
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(notes_router)
app.include_router(memories_router)
app.include_router(settings_router)
app.include_router(backups_router)
app.include_router(history_router)
app.include_router(templates_router)
app.include_router(billing_router)
app.include_router(technical_docs_router)
app.include_router(operations_router)
app.include_router(system_tools_router)
app.include_router(diagnostics_router)
app.include_router(documents_router)
app.include_router(calendar_router)
app.include_router(coding_router)
app.include_router(multi_agents_router)
app.include_router(workflows_router)
app.include_router(voice_router)
app.include_router(avatar_router)
app.include_router(vm_lab_router)
app.include_router(runtime_config_router)
app.include_router(skills_router)
app.include_router(content_router)
app.include_router(connections_router)
app.include_router(cron_monitor_router)
app.include_router(ssh_router)
app.include_router(storage_router)
app.include_router(health_router)


# v2.184 — filet GLOBAL pour toute exception qui s'échapperait d'une route SANS passer par
# le try/except dédié de /api/tools ou de la boucle agent (ex. un bug dans un endpoint qui
# n'a pas encore ce genre de garde). N'intercepte PAS les HTTPException (déjà gérées par
# Starlette avec leur propre code de statut) — seulement les crashes VRAIMENT non prévus,
# qui deviendraient sinon un 500 sec sans aucune trace nulle part. Demandé explicitement
# (« tout problème doit être logué pour pouvoir le debugger ») avant une période d'usage
# intensif sans nouvelle fonctionnalité.
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    try:
        import traceback as _tb
        import bug_log as _bug_log
        _bug_log.log_bug(
            "http_exception", str(exc),
            context={"path": str(request.url.path), "method": request.method},
            traceback_str=_tb.format_exc(),
        )
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"detail": f"Erreur interne : {exc}"})


# ══════════════════════════════════════════════════════════════════════════════
# Chat — SSE Streaming
# ══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    messages: list[dict]
    conversationId: str | None = None
    requestId: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    afterEvent: int = Field(default=0, ge=0)
    model: str | None = None
    cortex: dict | None = None


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.requestId:
        async def event_stream():
            async for chunk in run_agent(
                req.messages, req.conversationId, req.model, req.cortex,
            ):
                yield chunk
    else:
        fingerprint = chat_turn_runtime.payload_hash({
            "messages": req.messages,
            "conversationId": req.conversationId,
            "model": req.model,
            "cortex": req.cortex,
        })

        def producer():
            return run_agent(
                req.messages, req.conversationId, req.model, req.cortex,
                request_id=req.requestId,
            )

        async def event_stream():
            try:
                async for chunk in chat_turn_runtime.subscribe(
                    request_id=req.requestId,
                    fingerprint=fingerprint,
                    conversation_id=req.conversationId,
                    producer_factory=producer,
                    after_sequence=req.afterEvent,
                ):
                    yield chunk
            except ValueError as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Exécution manuelle d'un outil (confirmation utilisateur)
# ══════════════════════════════════════════════════════════════════════════════

class ToolExecuteRequest(BaseModel):
    toolName: str
    args: dict = Field(default_factory=dict)


@app.post("/api/tools")
async def execute_tool_endpoint(req: ToolExecuteRequest):
    executor = tool_module.TOOLS_REGISTRY.get(req.toolName)
    if not executor:
        raise HTTPException(status_code=404, detail=f"Outil « {req.toolName} » introuvable")

    # ── Vérification du niveau de permission ─────────────────────────────────
    try:
        perm_raw = db.get_setting("permission_level")
        permission_level = int(perm_raw) if perm_raw is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        permission_level = DEFAULT_PERMISSION_LEVEL

    if permission_level == PERMISSION_SECURE and req.toolName in SECURE_BLOCKED_TOOLS:
        return {
            "result": {
                "error": (
                    f"🛡️ Permission refusée (niveau Sécurisé) : "
                    f"l'outil '{req.toolName}' n'est pas autorisé dans ce mode. "
                    f"Passez en mode Standard ou Expert dans Paramètres > Permissions."
                )
            }
        }

    args = dict(req.args)
    # Niveau Expert ou confirmation manuelle → auto-confirm
    if req.toolName in DANGEROUS_TOOLS:
        args["confirmed"] = True
    if permission_level == PERMISSION_EXPERT:
        args["confirmed"] = True

    import time as _time
    t0 = _time.monotonic()
    try:
        result = await executor(args)
        duration_ms = int((_time.monotonic() - t0) * 1000)
        try:
            import engineering_runtime as _engineering_runtime
            result = _engineering_runtime.normalize_tool_result(
                req.toolName, result, duration_ms=duration_ms,
            )
        except Exception:
            pass
        try:
            db.log_execution(req.toolName, req.args, result, duration_ms)
        except Exception:
            pass
        try:
            import audit
            audit.log_action(req.toolName, req.args, result, source="ui")
        except Exception:
            pass
        return {"result": result}
    except Exception as e:
        try:
            import traceback as _tb
            import bug_log as _bug_log
            _bug_log.log_bug("tool_exception", str(e), context={"args": req.args},
                              traceback_str=_tb.format_exc(), tool_name=req.toolName)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tools/list")
async def list_tools_endpoint():
    """Catalogue complet des outils (nom/description/schéma) — audit + découverte
    externe (ex : le serveur MCP de Marvin, backend/mcp_server.py, lit ce catalogue
    sans jamais importer tools.py/database.py directement, pour ne pas risquer un
    conflit de verrou Qdrant mono-process)."""
    return {
        "tools": tool_module.TOOLS_SPEC,
        "count": len(tool_module.TOOLS_SPEC),
        "registry_synced": len(tool_module.TOOLS_REGISTRY) == len(tool_module.TOOLS_SPEC),
    }


@app.post("/api/mcp/execute")
async def execute_tool_mcp(req: ToolExecuteRequest):
    """
    Exécution d'outil pour des appelants EXTERNES (serveur MCP de Marvin →
    Claude Desktop, Cursor, etc.) — délibérément SÉPARÉE de /api/tools.

    Différence clé de sécurité : /api/tools force `confirmed=true` sur tout outil
    DANGEREUX, car c'est la page Outils qui a déjà demandé confirmation via son
    propre bouton/dialogue AVANT d'appeler cet endpoint. Un appelant MCP n'a rien
    demandé — le forcer aveuglément permettrait à un client MCP externe de
    déclencher des actions destructrices sans confirmation.

    Ici, seul le niveau de permission ACTUEL de Marvin (Sécurisé/Standard/Expert,
    réglé dans Paramètres) décide : en Expert, confirmation automatique (comme le
    reste de Marvin) ; sinon, l'outil renvoie normalement `requiresConfirmation`
    et c'est au client MCP (donc à l'utilisateur, côté Claude Desktop/Cursor) de
    rappeler avec confirmed=true s'il approuve. `security.screen_command()` reste
    de toute façon actif à l'intérieur de chaque outil (défense en profondeur).
    """
    executor = tool_module.TOOLS_REGISTRY.get(req.toolName)
    if not executor:
        raise HTTPException(status_code=404, detail=f"Outil « {req.toolName} » introuvable")

    try:
        perm_raw = db.get_setting("permission_level")
        permission_level = int(perm_raw) if perm_raw is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        permission_level = DEFAULT_PERMISSION_LEVEL

    if permission_level == PERMISSION_SECURE and req.toolName in SECURE_BLOCKED_TOOLS:
        return {"result": {
            "error": (
                f"🛡️ Permission refusée (niveau Sécurisé) : l'outil '{req.toolName}' "
                f"n'est pas autorisé dans ce mode. Passez en mode Standard ou Expert "
                f"dans Marvin > Paramètres > Permissions."
            )
        }}

    args = dict(req.args)
    if permission_level == PERMISSION_EXPERT:
        args["confirmed"] = True
    # PAS de force-confirm en Standard/Sécurisé — voir docstring.

    import time as _time
    t0 = _time.monotonic()
    try:
        result = await executor(args)
        duration_ms = int((_time.monotonic() - t0) * 1000)
        try:
            db.log_execution(req.toolName, req.args, result, duration_ms)
        except Exception:
            pass
        try:
            import audit
            audit.log_action(req.toolName, req.args, result, source="mcp")
        except Exception:
            pass
        return {"result": result}
    except Exception as e:
        try:
            import traceback as _tb
            import bug_log as _bug_log
            _bug_log.log_bug("tool_exception", str(e), context={"args": req.args},
                              traceback_str=_tb.format_exc(), tool_name=req.toolName)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mcp/config")
async def mcp_config():
    """
    Config MCP prête à copier, avec les chemins RÉELS de CETTE installation
    (jamais codés en dur) : `sys.executable` pointe toujours vers le python.exe
    du venv réellement utilisé par ce backend, où que Marvin soit installé.
    Sert la page /mcp (guide de connexion) — voir aussi CLAUDE.md §6.
    """
    import sys
    python_exe = sys.executable
    server_script = str((BACKEND_DIR / "mcp_server.py").resolve())

    try:
        perm_raw = db.get_setting("permission_level")
        permission_level = int(perm_raw) if perm_raw is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        permission_level = DEFAULT_PERMISSION_LEVEL

    perm_labels = {
        PERMISSION_SECURE:   {"label": "Sécurisé",  "note": "Les outils dangereux sont bloqués pour les appelants MCP."},
        PERMISSION_STANDARD: {"label": "Standard",  "note": "Les outils dangereux renvoient une demande de confirmation — le client MCP doit rappeler avec confirmed=true si son utilisateur approuve."},
        PERMISSION_EXPERT:   {"label": "Expert",    "note": "⚠️ Les outils dangereux s'exécutent SANS confirmation, y compris via MCP — comme le reste de Marvin en ce mode."},
    }

    config_snippet = {
        "mcpServers": {
            "marvin": {
                "command": python_exe,
                "args": [server_script],
            }
        }
    }
    import json as _json

    return {
        "python_executable": python_exe,
        "server_script": server_script,
        "permission_level": permission_level,
        "permission_info": perm_labels.get(permission_level, perm_labels[PERMISSION_STANDARD]),
        "config_json": _json.dumps(config_snippet, indent=2, ensure_ascii=False),
        "tools_count": len(tool_module.TOOLS_SPEC),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Mémoires
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Paramètres
# ══════════════════════════════════════════════════════════════════════════════

# v2.179 — point d'entrée UNIQUE pour "quel est le meilleur modèle cloud installé pour X ?"
# (general/code/vision), résolu EN DIRECT sur les modèles réellement installés (jamais un tag
# figé) — partagé par Réglages (app/settings/page.jsx::applyPreset) ET CONFIGURER-CLOUD-TOTAL.bat
# (déploiement serveur boutique), pour ne plus dupliquer/désynchroniser la logique de choix.
@app.get("/api/cloud/best-model")
async def get_best_cloud_model(need: str = "general"):
    import cloud_routing as _cr
    model = _cr.pick_best_cloud_model(need)
    return {"need": need, "model": model, "installed": _cr.list_installed_cloud_models()}


# ══════════════════════════════════════════════════════════════════════════════
# Sauvegardes (data/secretary.db) — v2.111
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Recherche sémantique
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Santé
# ══════════════════════════════════════════════════════════════════════════════

# ── Aperçu & lecture de fichiers (visionneuse intégrée à Marvin) ─────────────────────
# ══════════════════════════════════════════════════════════════════════════════
# Screenshot — retourne PNG base64 directement dans la web UI
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Upload image pour le chat
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Credentials OAuth & API Keys
# ══════════════════════════════════════════════════════════════════════════════

# ── Google OAuth flow ─────────────────────────────────────────────────────────

# ── Microsoft OAuth flow ──────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# Historique d'exécution
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Templates d'outils
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Jobs Cron
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Monitoring Live (SSE) — CPU, RAM, Disques
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# SSH Manager
# ══════════════════════════════════════════════════════════════════════════════

import io
import security as _security

class SSHConnectionCreate(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    password: str = ""
    private_key: str = ""       # contenu PEM de la clé privée (RSA/Ed25519/ECDSA/DSS)
    key_passphrase: str = ""    # v2.117 — passphrase optionnelle si la clé est chiffrée
    connection_id: str = ""     # optionnel, utilisé uniquement par /api/ssh/test pour persister le résultat


class SSHConnectionUpdate(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    password: str = ""          # vide = conserver le secret existant (cf. db.update_ssh_connection)
    private_key: str = ""
    key_passphrase: str = ""


class SSHCommandRequest(BaseModel):
    connection_id: str
    command: str
    timeout: int = 30


# Migré vers api/ssh.py
async def list_ssh():
    return db.list_ssh_connections()


# Migré vers api/ssh.py
async def create_ssh(body: SSHConnectionCreate):
    return db.save_ssh_connection(body.name, body.host, body.port, body.username,
                                   body.password, body.private_key, body.key_passphrase)


# Migré vers api/ssh.py
async def edit_ssh(sid: str, body: SSHConnectionUpdate):
    """v2.117 — édition d'une connexion existante (jusqu'ici seuls add/delete existaient,
    corriger un simple typo dans l'hôte obligeait à tout ressaisir)."""
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    updated = db.update_ssh_connection(sid, **body.model_dump())
    return updated


# Migré vers api/ssh.py
async def delete_ssh(sid: str):
    db.delete_ssh_connection(sid)
    return {"success": True}


# v2.117 — les 3 endpoints ci-dessous réimplémentaient CHACUN leur propre connexion paramiko
# en dur (RSA uniquement via `paramiko.RSAKey.from_private_key`, une clé Ed25519/ECDSA —
# le défaut de `ssh-keygen` depuis des années — échouait silencieusement) ET ne passaient
# JAMAIS par `security.screen_command()`, alors que CLAUDE.md §6 est explicite : « toute
# commande shell/PowerShell/SSH passe par screen_command() AVANT exécution ». Le terminal SSH
# de la page web (celui qu'un humain tape à la main) était donc le SEUL chemin d'exécution de
# commandes de tout Marvin à ne PAS avoir le garde-fou anti-catastrophe — la version pilotée
# par le chat (tools.py::execute_ssh_exec) l'avait déjà. Corrigé en délégant à
# `tool_module._ssh_connect`/`_ssh_load_key` (déjà multi-format) et en ajoutant le guard ici.
# Migré vers api/ssh.py
async def test_ssh(body: SSHConnectionCreate):
    """Teste la connectivité SSH. Si `connection_id` est fourni et qu'aucun secret n'est
    saisi dans le formulaire, réutilise le mot de passe/clé déjà en base (permet de tester
    une connexion sauvegardée sans ressaisir le secret — bouton 🧪 de la sidebar)."""
    password, private_key, key_passphrase = body.password, body.private_key, body.key_passphrase
    if body.connection_id and not password and not private_key:
        saved = db.get_ssh_connection(body.connection_id)
        if saved:
            password = saved.get("password") or ""
            private_key = saved.get("private_key") or ""
            key_passphrase = saved.get("key_passphrase") or ""

    def _run():
        client = tool_module._ssh_connect(dict(
            host=body.host, port=body.port, username=body.username,
            password=password, private_key=private_key,
            key_passphrase=key_passphrase,
        ), timeout=8)
        _, stdout, _ = client.exec_command("uname -a || ver", timeout=5)
        info = stdout.read().decode(errors="replace").strip()
        client.close()
        return info
    try:
        info = await _asyncio.get_running_loop().run_in_executor(None, _run)
        if body.connection_id:
            db.set_ssh_test_result(body.connection_id, True)
        return {"success": True, "info": info}
    except Exception as e:
        if body.connection_id:
            db.set_ssh_test_result(body.connection_id, False)
        return {"success": False, "error": str(e)}


# Migré vers api/ssh.py
async def exec_ssh(body: SSHCommandRequest):
    """Exécute une commande SSH et retourne stdout+stderr."""
    conn = db.get_ssh_connection(body.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")

    blocked = _security.guard_result(body.command)
    if blocked:
        return {"stdout": "", "stderr": blocked.get("error", "Commande bloquée."), "exit_code": -1, "command": body.command}

    def _run():
        client = tool_module._ssh_connect(conn, timeout=body.timeout)
        _, stdout, stderr = client.exec_command(body.command, timeout=body.timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        return {"stdout": out, "stderr": err, "exit_code": exit_code, "command": body.command}

    try:
        result = await _asyncio.get_running_loop().run_in_executor(None, _run)
        db.touch_ssh_connection(body.connection_id)
        try:
            db.log_execution("ssh_exec", {"connection_id": body.connection_id, "command": body.command}, result, 0)
        except Exception:
            pass
        return result
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1, "command": body.command}


# Migré vers api/ssh.py
async def exec_ssh_stream(connection_id: str, command: str):
    """Exécute une commande SSH en streaming SSE (ligne par ligne)."""
    conn = db.get_ssh_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")

    blocked = _security.guard_result(command)

    async def generate():
        if blocked:
            yield f"data: {json.dumps({'type':'error','message':blocked.get('error','Commande bloquée.')})}\n\n"
            return
        try:
            client = await _asyncio.get_running_loop().run_in_executor(None, tool_module._ssh_connect, conn, 30)
            _, stdout, stderr = client.exec_command(command, timeout=60)

            while True:
                line = await _asyncio.get_running_loop().run_in_executor(None, stdout.readline)
                if not line:
                    break
                yield f"data: {json.dumps({'type':'stdout','line':line.rstrip()})}\n\n"

            err = await _asyncio.get_running_loop().run_in_executor(None, stderr.read)
            if err:
                yield f"data: {json.dumps({'type':'stderr','line':err.decode(errors='replace').strip()})}\n\n"

            exit_code = stdout.channel.recv_exit_status()
            yield f"data: {json.dumps({'type':'done','exit_code':exit_code})}\n\n"
            db.touch_ssh_connection(connection_id)
            client.close()
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# v2.118 — Terminal interactif RÉEL (PTY), demandé explicitement (« je veux voir le
# terminal comme si j'y étais, peu importe Windows ou Linux »). `exec_ssh_stream`
# ci-dessus exécute une commande complète et attend sa fin — pas d'invite interactive,
# pas d'historique shell natif, pas de programmes plein écran (top, vim, moins…).
# Un vrai shell interactif s'ouvre via `paramiko.invoke_shell()` (canal PTY) et transmet
# les octets bruts dans les deux sens en continu — exactement ce que fait un client SSH
# natif (PuTTY, `ssh` en ligne de commande). Le protocole SSH délègue l'allocation du PTY
# au serveur distant : AUCUNE distinction Windows/Linux n'est nécessaire ici, le serveur
# OpenSSH (natif sous Windows 10+ ou sous Linux) gère lui-même le shell qu'il lance
# (cmd.exe/PowerShell ou bash/sh selon sa configuration).
# ⚠️ Contrepartie assumée : un flux d'octets bruts ne peut PAS être filtré par
# `security.screen_command()` sans casser l'interactivité (pas de "commande complète"
# identifiable avant que l'utilisateur appuie sur Entrée côté shell distant — même
# limitation que n'importe quel client SSH classique). Le garde-fou reste entier sur tous
# les chemins d'exécution AUTOMATISÉS de Marvin (chat, exec/stream ci-dessus) — ce canal-ci
# est un clavier direct tenu par un humain déjà authentifié sur sa propre connexion SSH
# sauvegardée, équivalent à ouvrir PuTTY.
# Migré vers api/ssh.py
async def ssh_shell_ws(websocket: WebSocket, sid: str):
    await websocket.accept()
    conn = db.get_ssh_connection(sid)
    if not conn:
        await websocket.send_json({"type": "error", "message": "Connexion introuvable."})
        await websocket.close()
        return

    loop = _asyncio.get_running_loop()
    client = None
    channel = None
    try:
        client = await loop.run_in_executor(None, tool_module._ssh_connect, conn, 15)
        channel = await loop.run_in_executor(
            None, lambda: client.invoke_shell(term="xterm-256color", width=80, height=24)
        )
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        await websocket.close()
        return

    db.touch_ssh_connection(sid)

    def _blocking_recv():
        try:
            return channel.recv(4096)
        except Exception:
            return None

    async def pump_ssh_to_ws():
        try:
            while True:
                data = await loop.run_in_executor(None, _blocking_recv)
                if not data:
                    break
                await websocket.send_json({"type": "data", "data": data.decode(errors="replace")})
        except Exception:
            pass
        try:
            await websocket.send_json({"type": "closed"})
        except Exception:
            pass

    reader_task = _asyncio.create_task(pump_ssh_to_ws())
    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "input":
                # channel.send() attend des bytes — un envoi en str compterait la taille de
                # la fenêtre en caractères et non en octets, risquant de tronquer un
                # caractère accentué/multi-octets en UTF-8 au milieu de sa séquence.
                channel.send(msg.get("data", "").encode("utf-8"))
            elif mtype == "resize":
                try:
                    channel.resize_pty(width=int(msg.get("cols", 80)), height=int(msg.get("rows", 24)))
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        reader_task.cancel()
        try: channel.close()
        except Exception: pass
        try: client.close()
        except Exception: pass


# ── v2.117 : navigateur SFTP + diagnostic serveur — la logique existait déjà côté outils
# chat (tools.py::execute_ssh_list_dir/server_info) mais était injoignable depuis la page
# /ssh. Réutilisée directement (lecture seule, aucune confirmation nécessaire). ──────────
# Migré vers api/ssh.py
async def browse_ssh(sid: str, path: str = "."):
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    return await tool_module.execute_ssh_list_dir({"connection_id": sid, "remote_path": path})


# Migré vers api/ssh.py
async def ssh_server_info(sid: str):
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    return await tool_module.execute_ssh_server_info({"connection_id": sid})


# Migré vers api/ssh.py
async def download_ssh_file(sid: str, path: str):
    """Télécharge un fichier distant DIRECTEMENT dans le navigateur (pas sur le disque de
    Marvin — contrairement à l'outil chat `ssh_download` qui sauvegarde côté serveur)."""
    conn = db.get_ssh_connection(sid)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")

    def _run():
        client = tool_module._ssh_connect(conn, timeout=30)
        sftp = client.open_sftp()
        buf = io.BytesIO()
        sftp.getfo(path, buf)
        sftp.close(); client.close()
        return buf.getvalue()

    try:
        data = await _asyncio.get_running_loop().run_in_executor(None, _run)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    filename = path.rstrip("/").rsplit("/", 1)[-1] or "download"
    return Response(content=data, media_type="application/octet-stream",
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# Migré vers api/ssh.py
async def upload_ssh_file(sid: str, remote_path: str = Form(...), file: UploadFile = File(...)):
    """Envoie un fichier depuis le navigateur vers le serveur distant (SFTP)."""
    conn = db.get_ssh_connection(sid)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    content = await file.read()

    def _run():
        client = tool_module._ssh_connect(conn, timeout=60)
        sftp = client.open_sftp()
        sftp.putfo(io.BytesIO(content), remote_path)
        size = sftp.stat(remote_path).st_size
        sftp.close(); client.close()
        return size

    try:
        size = await _asyncio.get_running_loop().run_in_executor(None, _run)
        db.touch_ssh_connection(sid)
        return {"success": True, "remote_path": remote_path, "size": size}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Email Manager (IMAP + SMTP)
# ══════════════════════════════════════════════════════════════════════════════

import email_manager as _em
import email_accounts as _email_accounts

def _coerce_json(v):
    if isinstance(v, str):
        try:
            import json as _json
            return _json.loads(v)
        except Exception:
            return None
    return v


def _get_email_accounts() -> list[dict]:
    """Liste résolue des comptes email (mot de passe ou jeton OAuth frais)."""
    return _email_accounts.list_resolved()


def _save_email_accounts(accts: list[dict]) -> None:
    _email_accounts.save(accts)


def _upsert_email_account(cfg: dict) -> list[dict]:
    return _email_accounts.upsert(cfg)


def _get_email_config(account: str | None = None) -> dict | None:
    return _email_accounts.get(account, resolved=True)


class EmailConfig(BaseModel):
    provider: str = "custom"
    imap_host: str
    imap_port: int = 993
    smtp_host: str
    smtp_port: int = 587
    username: str
    password: str


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: str = ""
    reply_to: str = ""
    html_body: str = ""


@app.get("/api/email/providers")
async def email_providers():
    return _em.PROVIDERS


@app.get("/api/email/config")
async def get_email_config(account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        return {"configured": False}
    # Ne pas retourner le mot de passe en clair
    secret_fields = {"password", "access_token", "refresh_token", "oauth_client_secret"}
    safe = {k: v for k, v in cfg.items() if k not in secret_fields and not k.startswith("_")}
    safe["configured"] = True
    safe["password_set"] = bool(cfg.get("password"))
    return safe


@app.post("/api/email/config")
async def set_email_config(body: EmailConfig):
    # Ajoute ou met à jour le compte (multi-comptes) au lieu d'écraser.
    _upsert_email_account({**body.model_dump(), "auth_type": "app_password"})
    return {"success": True}


# ── Multi-comptes email ───────────────────────────────────────────────────────
@app.get("/api/email/accounts")
async def email_accounts_list():
    """Liste des boîtes mail connectées (sans les mots de passe)."""
    accts = _email_accounts.list_raw()
    return {
        "accounts": [_email_accounts.public(a) for a in accts],
        "default": accts[0].get("username") if accts else None,
        "count": len(accts),
    }


@app.post("/api/email/accounts")
async def email_accounts_add(body: EmailConfig):
    """Ajoute (ou met à jour) une boîte mail sans toucher aux autres."""
    accts = _upsert_email_account({**body.model_dump(), "auth_type": "app_password"})
    return {"success": True, "id": body.username, "count": len(accts)}


@app.delete("/api/email/accounts/{account_id}")
async def email_accounts_remove(account_id: str):
    """Déconnecte une boîte mail précise."""
    removed = _email_accounts.remove(account_id)
    return {"success": True, "removed": removed, "count": len(_email_accounts.list_raw())}


@app.post("/api/email/test")
async def test_email_config(body: EmailConfig):
    def _test():
        return _em.test_connection(
            body.imap_host, body.imap_port,
            body.smtp_host, body.smtp_port,
            body.username, body.password,
        )
    result = await _asyncio.get_running_loop().run_in_executor(None, _test)
    return result


@app.get("/api/email/inbox")
async def email_inbox(folder: str = "INBOX", limit: int = 30, offset: int = 0, account: str | None = None):
    loop = _asyncio.get_running_loop()
    # ── Boîte UNIFIÉE : agrège toutes les boîtes (account=__all__) ──
    if account == "__all__":
        accts = _get_email_accounts()
        if not accts:
            return {"error": "Email non configuré", "emails": []}

        async def _fetch_one(a):
            try:
                ems = await loop.run_in_executor(None, lambda: _em.fetch_inbox(
                    a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                    folder=folder, limit=limit, offset=0))
                for e in ems:
                    e["_account"] = a["username"]
                return ems
            except Exception:
                return []

        results = await _asyncio.gather(*[_fetch_one(a) for a in accts])
        merged = [e for sub in results for e in sub]
        merged.sort(key=lambda e: e.get("date") or "", reverse=True)
        return {"emails": merged[: max(limit, 30) * 2], "folder": folder, "unified": True}

    # ── Boîte unique ──
    cfg = _get_email_config(account)
    if not cfg:
        return {"error": "Email non configuré", "emails": []}
    def _fetch():
        ems = _em.fetch_inbox(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
            folder=folder, limit=limit, offset=offset,
        )
        for e in ems:
            e["_account"] = cfg["username"]
        return ems
    try:
        emails = await loop.run_in_executor(None, _fetch)
        return {"emails": emails, "folder": folder}
    except Exception as e:
        return {"error": str(e), "emails": []}


@app.get("/api/email/read/{uid}")
async def email_read(uid: str, folder: str = "INBOX", account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _fetch():
        return _em.fetch_email(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
            uid=uid, folder=folder,
        )
    try:
        return await _asyncio.get_running_loop().run_in_executor(None, _fetch)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/email/search")
async def email_search(q: str, folder: str = "INBOX", limit: int = 20, account: str | None = None):
    loop = _asyncio.get_running_loop()
    # Recherche unifiée sur toutes les boîtes
    if account == "__all__":
        accts = _get_email_accounts()
        async def _search_one(a):
            try:
                rs = await loop.run_in_executor(None, lambda: _em.search_emails(
                    a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                    query=q, folder=folder, limit=limit))
                for e in rs:
                    e["_account"] = a["username"]
                return rs
            except Exception:
                return []
        results = await _asyncio.gather(*[_search_one(a) for a in accts])
        merged = [e for sub in results for e in sub]
        merged.sort(key=lambda e: e.get("date") or "", reverse=True)
        return {"results": merged, "unified": True}

    cfg = _get_email_config(account)
    if not cfg:
        return {"results": [], "error": "Email non configuré"}
    def _search():
        rs = _em.search_emails(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
            query=q, folder=folder, limit=limit,
        )
        for e in rs:
            e["_account"] = cfg["username"]
        return rs
    try:
        results = await loop.run_in_executor(None, _search)
        return {"results": results}
    except Exception as e:
        return {"results": [], "error": str(e)}


@app.get("/api/email/folders")
async def email_folders(account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        return {"folders": []}
    def _list():
        return _em.list_folders(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"]
        )
    try:
        folders = await _asyncio.get_running_loop().run_in_executor(None, _list)
        return {"folders": folders}
    except Exception as e:
        return {"folders": [], "error": str(e)}


@app.post("/api/email/send")
async def email_send(body: SendEmailRequest, account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _send():
        return _em.send_email(
            cfg["smtp_host"], cfg["smtp_port"], cfg["username"], cfg["password"],
            to=body.to, subject=body.subject, body=body.body,
            cc=body.cc, reply_to=body.reply_to, html_body=body.html_body,
        )
    try:
        result = await _asyncio.get_running_loop().run_in_executor(None, _send)
        db.log_execution("email_send", {"to": body.to, "subject": body.subject}, result, 0)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/email/{uid}")
async def email_delete(uid: str, folder: str = "INBOX", account: str | None = None):
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _del():
        _em.delete_email(
            cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
            uid=uid, folder=folder,
        )
    await _asyncio.get_running_loop().run_in_executor(None, _del)
    return {"success": True}


@app.post("/api/email/mark")
async def email_mark(uid: str, seen: bool = True, folder: str = "INBOX", account: str | None = None):
    """Marque un email comme lu/non lu."""
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _m():
        _em.mark_email(cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
                       uid=uid, folder=folder, seen=seen)
    try:
        await _asyncio.get_running_loop().run_in_executor(None, _m)
        return {"success": True, "seen": seen}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/move")
async def email_move(uid: str, dest: str, folder: str = "INBOX", account: str | None = None):
    """Déplace un email vers un autre dossier (archiver = déplacer vers Archive/All Mail)."""
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _mv():
        _em.move_email(cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
                       uid=uid, dest_folder=dest, folder=folder)
    try:
        await _asyncio.get_running_loop().run_in_executor(None, _mv)
        return {"success": True, "dest": dest}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Signatures (par boîte) ────────────────────────────────────────────────────
def _coerce_obj(v, default):
    if isinstance(v, str):
        import json as _json
        try: return _json.loads(v)
        except Exception: return default
    return v if v is not None else default


@app.get("/api/email/signatures")
async def get_signatures():
    return {"signatures": _coerce_obj(db.get_setting("email_signatures"), {})}


@app.post("/api/email/signatures")
async def set_signatures(body: dict = Body(...)):
    sigs = _coerce_obj(db.get_setting("email_signatures"), {})
    acc = (body.get("account") or "").strip()
    if not acc:
        raise HTTPException(status_code=400, detail="account requis")
    sigs[acc] = body.get("signature", "")
    db.set_setting("email_signatures", sigs)
    return {"success": True}


# ── Modèles de réponse réutilisables ──────────────────────────────────────────
@app.get("/api/email/templates")
async def get_templates():
    t = _coerce_obj(db.get_setting("email_templates"), [])
    return {"templates": t if isinstance(t, list) else []}


@app.post("/api/email/templates")
async def add_template(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    content = body.get("body", "")
    if not name:
        raise HTTPException(status_code=400, detail="nom requis")
    t = _coerce_obj(db.get_setting("email_templates"), [])
    if not isinstance(t, list):
        t = []
    t = [x for x in t if x.get("name") != name]  # remplace si même nom
    t.append({"name": name, "body": content})
    db.set_setting("email_templates", t[-50:])
    return {"success": True, "count": len(t)}


@app.delete("/api/email/templates/{name}")
async def delete_template(name: str):
    t = _coerce_obj(db.get_setting("email_templates"), [])
    if not isinstance(t, list):
        t = []
    new = [x for x in t if x.get("name") != name]
    db.set_setting("email_templates", new)
    return {"success": True, "count": len(new)}


# ── Surveillance intelligente des mails importants (notifications) ────────────
@app.get("/api/email/watch")
async def get_email_watch():
    return _coerce_obj(db.get_setting("email_watch"), {"enabled": False, "interval_min": 5, "accounts": [], "max_notify": 5})


@app.post("/api/email/watch")
async def set_email_watch(body: dict = Body(...)):
    db.set_setting("email_watch", body)
    return {"success": True, "enabled": bool(body.get("enabled"))}


@app.post("/api/email/watch/run")
async def run_email_watch():
    """Vérifie maintenant (force) les mails importants et notifie."""
    return await tool_module.TOOLS_REGISTRY["email_watch_check"]({"force": True})


@app.get("/api/email/watch/alerts")
async def get_email_alerts():
    return {"alerts": _coerce_obj(db.get_setting("email_watch_alerts"), [])}


@app.post("/api/email/watch/alerts/clear")
async def clear_email_alerts():
    db.set_setting("email_watch_alerts", [])
    return {"success": True}


# ── Règles de classement automatique ─────────────────────────────────────────
@app.get("/api/email/rules")
async def get_email_rules():
    return {"rules": _coerce_obj(db.get_setting("email_rules"), [])}


@app.post("/api/email/rules")
async def set_email_rules(body: dict = Body(...)):
    rules = body.get("rules", [])
    db.set_setting("email_rules", rules if isinstance(rules, list) else [])
    return {"success": True, "count": len(rules) if isinstance(rules, list) else 0}


@app.post("/api/email/rules/run")
async def run_email_rules(dry_run: bool = False, account: str | None = None):
    return await tool_module.TOOLS_REGISTRY["email_apply_rules"]({"dry_run": dry_run, "account": account})


# ── Briefing du jour ──────────────────────────────────────────────────────────
@app.get("/api/briefing")
async def daily_briefing():
    """Briefing du jour : emails non lus + tâches en attente, synthèse IA."""
    result = await tool_module.TOOLS_REGISTRY["daily_briefing"]({})
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ── Marvin proactif (briefing matinal automatique) ─────────────────────────────
@app.get("/api/proactive")
async def get_proactive():
    return _proactive_with_defaults(_get_proactive_cfg())


@app.post("/api/proactive")
async def set_proactive(body: dict = Body(...)):
    cfg = _proactive_with_defaults(_get_proactive_cfg())
    # Bloc morning_briefing (rétro-compat : l'ancienne UI postait les champs au top-level)
    if "morning_briefing" in body:
        inc = body["morning_briefing"]
    elif not any(k in body for k in ("evening_recap", "anticipation")):
        inc = body
    else:
        inc = {}
    mb = cfg["morning_briefing"]
    mb.update({k: inc[k] for k in ("enabled", "time", "voice", "voice_name") if k in inc})
    # Bloc evening_recap
    if "evening_recap" in body:
        er = cfg["evening_recap"]; inc = body["evening_recap"]
        er.update({k: inc[k] for k in ("enabled", "time", "voice", "voice_name") if k in inc})
    # Bloc anticipation
    if "anticipation" in body:
        an = cfg["anticipation"]; inc = body["anticipation"]
        an.update({k: inc[k] for k in ("enabled", "interval_min", "overdue_tasks", "upcoming_events",
                                       "upcoming_events_min", "max_notify") if k in inc})
    if "quiet_hours" in body:
        qh = cfg["quiet_hours"]; inc = body["quiet_hours"]
        qh.update({k: inc[k] for k in ("enabled", "start", "end") if k in inc})
    db.set_setting("proactive_config", cfg)
    return {"success": True, "config": cfg}


@app.post("/api/proactive/run")
async def run_proactive_now(kind: str = "morning"):
    """Déclenche immédiatement (test) : kind = morning | evening | anticipation."""
    cfg = _proactive_with_defaults(_get_proactive_cfg())
    if kind == "evening":
        return await run_evening_recap(cfg["evening_recap"])
    if kind == "anticipation":
        return await run_anticipation(cfg["anticipation"], force=True)
    return await run_morning_briefing(cfg["morning_briefing"])


# ── Telegram (alertes sur le téléphone) ─────────────────────────────────────────
# ── Accès réseau / mobile (IP à jour automatiquement) ──────────────────────────
# ── Apprentissage : ce que Marvin a appris ─────────────────────────────────────
# ── Auto-configuration des modèles selon le matériel ──────────────────────────
# ── Skills (compétences ajoutables en Markdown, façon Claude Code, sans coder) ───────
# ── Documents (RAG : parle à tes documents) ────────────────────────────────────
# ── Agenda local (événements) ─────────────────────────────────────────────────
# ── Agendas connectés (abonnements iCal) ────────────────────────────────────────
class DraftReplyRequest(BaseModel):
    uid: str = ""
    body: str = ""
    subject: str = ""
    from_: str = Field("", alias="from")
    instruction: str = ""
    tone: str = ""
    folder: str = "INBOX"
    account: str = ""
    model_config = {"populate_by_name": True}


@app.post("/api/email/draft-reply")
async def email_draft_reply(body: DraftReplyRequest):
    """Génère par IA un brouillon de réponse (ne l'envoie pas)."""
    args = {
        "uid": body.uid, "body": body.body, "subject": body.subject,
        "from": body.from_, "instruction": body.instruction, "tone": body.tone,
        "folder": body.folder, "account": body.account or None,
    }
    result = await tool_module.TOOLS_REGISTRY["email_draft_reply"](args)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


class SummarizeRequest(BaseModel):
    uid: str = ""
    body: str = ""
    subject: str = ""
    from_: str = Field("", alias="from")
    folder: str = "INBOX"
    account: str = ""
    model_config = {"populate_by_name": True}


@app.post("/api/email/summarize")
async def email_summarize(body: SummarizeRequest):
    """Résume un email par IA."""
    args = {"uid": body.uid, "body": body.body, "subject": body.subject,
            "from": body.from_, "folder": body.folder, "account": body.account or None}
    result = await tool_module.TOOLS_REGISTRY["email_summarize"](args)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/email/digest")
async def email_digest(account: str | None = None, limit: int = 15, folder: str = "INBOX"):
    """Briefing IA priorisé de la boîte (ou de toutes via account=__all__)."""
    result = await tool_module.TOOLS_REGISTRY["email_digest"](
        {"account": account, "limit": limit, "folder": folder})
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ── Assistant email automatique (3 modes) ────────────────────────────────────
class AutomationConfig(BaseModel):
    mode: str = "manuel"                 # manuel | brouillon | differe | autonome
    accounts: list[str] = Field(default_factory=list)
    instructions: str = ""
    tone: str = "professionnel, clair et courtois"
    signature: str = ""
    only_from: list[str] = Field(default_factory=list)
    never_from: list[str] = Field(default_factory=list)
    skip_keywords: list[str] = Field(default_factory=list)
    max_per_run: int = 5
    send_delay_min: int = 5
    scheduler_enabled: bool = False
    scheduler_confirmed: bool = False
    interval_min: int = 5
    profiles: dict[str, dict] = Field(default_factory=dict)


@app.get("/api/email/automation")
async def get_email_automation():
    cfg = db.get_setting("email_automation")
    if isinstance(cfg, str):
        import json as _json
        try: cfg = _json.loads(cfg)
        except Exception: cfg = None
    if not isinstance(cfg, dict):
        cfg = {"mode": "manuel"}
    return {"scheduler_enabled": False, "interval_min": 5, "profiles": {}, **cfg}


@app.post("/api/email/automation")
async def set_email_automation(body: AutomationConfig):
    previous = db.get_setting("email_automation") or {}
    if isinstance(previous, str):
        try: previous = json.loads(previous)
        except Exception: previous = {}
    was_enabled = bool(previous.get("scheduler_enabled")) if isinstance(previous, dict) else False
    if body.scheduler_enabled and not was_enabled and not body.scheduler_confirmed:
        raise HTTPException(status_code=409, detail="Confirmation explicite requise pour activer les envois automatiques en arrière-plan.")
    data = body.model_dump(exclude={"scheduler_confirmed"})
    data["interval_min"] = max(2, min(int(data["interval_min"]), 1440))
    data["max_per_run"] = max(1, min(int(data["max_per_run"]), 100))
    data["send_delay_min"] = max(1, min(int(data["send_delay_min"]), 1440))
    db.set_setting("email_automation", data)
    return {"success": True, "mode": body.mode, "scheduler_enabled": body.scheduler_enabled}


@app.post("/api/email/automation/run")
async def run_email_automation(dry_run: bool = False, mode: str | None = None):
    """Lance le traitement maintenant (brouillons ou envoi autonome selon le mode)."""
    result = await tool_module.TOOLS_REGISTRY["email_automation_run"](
        {"dry_run": dry_run, "mode": mode, "source": "manual"})
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/email/automation/status")
async def email_automation_status():
    cfg = tool_module._email_automation_cfg()
    history = db.get_setting("email_automation_runs") or []
    if not isinstance(history, list):
        history = []
    return {
        "scheduler_enabled": cfg.get("scheduler_enabled", False),
        "interval_min": cfg.get("interval_min", 5),
        "selected_accounts": cfg.get("accounts", []),
        "last_run": history[-1] if history else None,
    }


@app.get("/api/email/automation/drafts")
async def get_pending_drafts():
    drafts = db.get_setting("email_pending_drafts")
    if isinstance(drafts, str):
        import json as _json
        try: drafts = _json.loads(drafts)
        except Exception: drafts = []
    return {"drafts": drafts if isinstance(drafts, list) else []}


@app.post("/api/email/automation/drafts/clear")
async def clear_pending_drafts():
    db.set_setting("email_pending_drafts", [])
    return {"success": True}


@app.get("/api/email/automation/outbox")
async def get_email_automation_outbox():
    outbox = db.get_setting("email_scheduled_outbox") or []
    return {"outbox": outbox if isinstance(outbox, list) else []}


@app.delete("/api/email/automation/outbox/{item_id}")
async def cancel_email_automation_outbox(item_id: str):
    outbox = db.get_setting("email_scheduled_outbox") or []
    if not isinstance(outbox, list):
        outbox = []
    remaining = [item for item in outbox if item.get("id") != item_id]
    if len(remaining) == len(outbox):
        raise HTTPException(status_code=404, detail="Envoi différé introuvable")
    db.set_setting("email_scheduled_outbox", remaining)
    return {"success": True, "cancelled": item_id}


@app.post("/api/email/to-task")
async def email_to_task(body: SummarizeRequest):
    """Transforme un email en tâche actionnable (IA)."""
    args = {"uid": body.uid, "body": body.body, "subject": body.subject,
            "from": body.from_, "folder": body.folder, "account": body.account or None}
    result = await tool_module.TOOLS_REGISTRY["email_to_task"](args)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/email/attachment")
async def email_attachment(uid: str, name: str = "", account: str | None = None, folder: str = "INBOX"):
    """Télécharge une pièce jointe d'un email."""
    cfg = _get_email_config(account)
    if not cfg:
        raise HTTPException(status_code=400, detail="Email non configuré")
    def _f():
        return _em.fetch_attachment(cfg["imap_host"], cfg["imap_port"], cfg["username"], cfg["password"],
                                    uid=uid, name=name, folder=folder)
    att = await _asyncio.get_running_loop().run_in_executor(None, _f)
    if not att or not att.get("data"):
        raise HTTPException(status_code=404, detail="Pièce jointe introuvable")
    import urllib.parse as _up
    fn = _up.quote(att["name"] or "piece_jointe")
    return Response(content=att["data"], media_type=att.get("content_type", "application/octet-stream"),
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"})


@app.get("/api/email/attachment/summary")
async def email_attachment_summary(uid: str, name: str = "", account: str | None = None, folder: str = "INBOX"):
    """Résume par IA une pièce jointe (PDF, Word, texte)."""
    result = await tool_module.TOOLS_REGISTRY["email_attachment_summary"](
        {"uid": uid, "name": name, "account": account or None, "folder": folder})
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Multi-agents — exécution parallèle d'outils avec SSE
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Workflows — enchaînement d'outils
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Transcription vocale — Whisper local (faster-whisper)
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Génération vidéo — Text-to-Video / Image-to-Video / Slideshow local
# ══════════════════════════════════════════════════════════════════════════════

import video_manager as _vm
import os as _os


@app.get("/api/video/models")
async def video_models():
    """Retourne les modèles disponibles pour text-to-video et image-to-video."""
    return {
        "text_to_video": _vm.TEXT_TO_VIDEO_MODELS,
        "image_to_video": _vm.IMAGE_TO_VIDEO_MODELS,
    }


class VideoGenerateTextRequest(BaseModel):
    model_key: str
    prompt: str
    extra_params: dict = Field(default_factory=dict)


@app.post("/api/video/generate/text")
async def video_generate_text(body: VideoGenerateTextRequest):
    """Lance une génération text-to-video sur Replicate et retourne le prediction_id."""
    import credentials_manager as cm

    model = _vm.TEXT_TO_VIDEO_MODELS.get(body.model_key)
    if not model:
        raise HTTPException(status_code=404, detail=f"Modèle inconnu : {body.model_key}")

    if model["provider"] == "replicate":
        api_token = cm.get_credential("replicate_api_token")
        if not api_token:
            raise HTTPException(
                status_code=400,
                detail="Token Replicate non configuré (Paramètres > Connexions)",
            )
        params = {**model["params"], "prompt": body.prompt, **body.extra_params}
        try:
            data = await _vm._replicate_start(model["model_id"], params, api_token)
            return {
                "success": True,
                "prediction_id": data["id"],
                "status": data.get("status", "starting"),
                "provider": "replicate",
                "model_name": model["name"],
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail=f"Provider non supporté : {model['provider']}")


@app.post("/api/video/generate/image")
async def video_generate_image(
    model_key: str = Form(...),
    prompt: str = Form(""),
    image: UploadFile = File(...),
):
    """Lance une génération image-to-video depuis un fichier image uploadé."""
    import credentials_manager as cm
    import tempfile

    model = _vm.IMAGE_TO_VIDEO_MODELS.get(model_key)
    if not model:
        raise HTTPException(status_code=404, detail=f"Modèle inconnu : {model_key}")

    # Déduire l'extension
    ext = ".jpg"
    if image.content_type:
        if "png"  in image.content_type: ext = ".png"
        elif "webp" in image.content_type: ext = ".webp"
        elif "gif"  in image.content_type: ext = ".gif"

    img_bytes = await image.read()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        img_uri = _vm.image_to_data_uri(tmp_path)

        if model["provider"] == "replicate":
            api_token = cm.get_credential("replicate_api_token")
            if not api_token:
                raise HTTPException(status_code=400, detail="Token Replicate non configuré")

            params = dict(model["params"])
            # Injecter l'image dans le champ attendu par le modèle
            for field in ("input_image", "image", "first_frame_image"):
                if field in params:
                    params[field] = img_uri
                    break
            if "prompt" in params:
                params["prompt"] = prompt

            data = await _vm._replicate_start(model["model_id"], params, api_token)
            return {
                "success": True,
                "prediction_id": data["id"],
                "status": data.get("status", "starting"),
                "provider": "replicate",
                "model_name": model["name"],
            }
        else:
            raise HTTPException(status_code=400, detail=f"Provider non supporté : {model['provider']}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass


@app.get("/api/video/status/{prediction_id}")
async def video_status_stream(prediction_id: str):
    """SSE : stream l'état d'une prédiction Replicate jusqu'à la fin."""
    import credentials_manager as cm

    api_token = cm.get_credential("replicate_api_token")
    if not api_token:
        raise HTTPException(status_code=400, detail="Token Replicate non configuré")

    async def generate():
        async for event in _vm.poll_replicate_sse(prediction_id, api_token):
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/video/cancel/{prediction_id}")
async def video_cancel(prediction_id: str):
    """Annule une prédiction Replicate en cours."""
    import credentials_manager as cm
    api_token = cm.get_credential("replicate_api_token")
    if not api_token:
        raise HTTPException(status_code=400, detail="Token Replicate non configuré")
    await _vm._replicate_cancel(prediction_id, api_token)
    return {"success": True}


@app.post("/api/video/download")
async def video_download_url(request: Request):
    """Télécharge et sauvegarde une vidéo générée depuis une URL externe."""
    body = await request.json()
    url = body.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL requise")
    try:
        path = await _vm.download_video(url)
        filename = _os.path.basename(path)
        size = _os.path.getsize(path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": _vm._fmt_size(size),
            "url": f"/api/video/files/{filename}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/video/slideshow")
async def video_slideshow(
    images: list[UploadFile] = File(...),
    format: str = Form("gif"),
    duration: float = Form(2.0),
    transition_frames: int = Form(8),
    fps: int = Form(24),
    fade_duration: float = Form(0.5),
    width: int = Form(640),
    height: int = Form(480),
):
    """Crée un diaporama GIF ou MP4 depuis des images uploadées (100% local, sans API)."""
    import tempfile

    if not images:
        raise HTTPException(status_code=400, detail="Au moins une image requise")

    tmp_paths = []
    try:
        for img in images:
            img_bytes = await img.read()
            ext = ".jpg"
            if img.content_type:
                if "png"  in img.content_type: ext = ".png"
                elif "webp" in img.content_type: ext = ".webp"
                elif "gif"  in img.content_type: ext = ".gif"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_paths.append(tmp.name)

        resize_to = (width, height)

        if format.lower() == "mp4":
            out_path = await _asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _vm.create_slideshow_mp4(
                    tmp_paths,
                    duration_per_image=duration,
                    fps=fps,
                    resize_to=resize_to,
                    fade_duration=fade_duration,
                ),
            )
        else:
            out_path = await _asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _vm.create_slideshow_gif(
                    tmp_paths,
                    duration_per_frame=duration,
                    resize_to=resize_to,
                    transition_frames=transition_frames,
                ),
            )

        filename = _os.path.basename(out_path)
        size = _os.path.getsize(out_path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": _vm._fmt_size(size),
            "format": format.upper(),
            "url": f"/api/video/files/{filename}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in tmp_paths:
            try:
                _os.unlink(p)
            except Exception:
                pass


class VideoTextAnimRequest(BaseModel):
    text: str
    style: str = "typewriter"     # typewriter | fade | scroll | title
    duration: float = 5.0
    fps: int = 24
    width: int = 854
    height: int = 480
    output_format: str = "mp4"    # mp4 | gif
    font_size: int = 40


@app.post("/api/video/text-animation")
async def video_text_animation(body: VideoTextAnimRequest):
    """Génère une vidéo animée depuis un texte (100% local, sans GPU ni API)."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Texte requis")
    try:
        out_path = await _asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _vm.create_text_animation_video(
                text=body.text,
                style=body.style,
                fps=body.fps,
                duration=body.duration,
                width=body.width,
                height=body.height,
                font_size=body.font_size,
                output_format=body.output_format,
            ),
        )
        filename = _os.path.basename(out_path)
        size = _os.path.getsize(out_path)
        return {
            "success": True,
            "filename": filename,
            "size": size,
            "size_human": _vm._fmt_size(size),
            "format": _os.path.splitext(filename)[1].lstrip(".").upper(),
            "url": f"/api/video/files/{filename}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/video/files")
async def list_video_files():
    """Liste toutes les vidéos générées (MP4, GIF, WebM)."""
    files = _vm.list_generated_videos()
    return {"files": files, "count": len(files)}


@app.get("/api/video/files/{filename}")
async def serve_video_file(filename: str):
    """Sert un fichier vidéo généré (streaming HTTP)."""
    path = _vm.get_video_dir() / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    ext = path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".gif": "image/gif",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
    }
    return FileResponse(
        str(path),
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=filename,
    )


@app.delete("/api/video/files/{filename}")
async def delete_video_file(filename: str):
    """Supprime un fichier vidéo généré."""
    path = _vm.get_video_dir() / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    path.unlink()
    return {"success": True}


# ══════════════════════════════════════════════════════════════════════════════
# v2.32 — Édition / Conversion vidéo & GIF (ffmpeg local, sans GPU ni API)
# ══════════════════════════════════════════════════════════════════════════════

def _video_edit_result(res: dict) -> dict:
    """Normalise un retour de video_manager → ajoute filename + url servable."""
    if not res or res.get("error"):
        raise HTTPException(status_code=500, detail=(res or {}).get("error", "Échec du traitement"))
    out = dict(res)
    path = res.get("path")
    if path:
        fn = _os.path.basename(path)
        out["filename"] = fn
        out["url"] = f"/api/video/files/{fn}"
    return out


@app.post("/api/video/edit")
async def video_edit(
    operation: str = Form(...),
    file: UploadFile = File(None),
    fps: float = Form(None),
    width: int = Form(None),
    height: int = Form(None),
    start: float = Form(None),
    end: float = Form(None),
    duration: float = Form(None),
    crf: int = Form(None),
    scale_width: int = Form(None),
    factor: float = Form(None),
    colors: int = Form(None),
    text: str = Form(None),
    position: str = Form("bottom-right"),
    font_size: int = Form(24),
    region: str = Form(None),       # "x,y,w,h"
    max_frames: int = Form(30),
):
    """
    Édition vidéo/GIF locale via ffmpeg (sans GPU ni API).
    operation ∈ {info, to_gif, gif_to_video, trim, compress, resize,
                 extract_frames, speed, watermark, optimize_gif, screen_record}
    Pour screen_record aucun fichier n'est requis.
    """
    import tempfile

    op = (operation or "").strip().lower()
    needs_file = op != "screen_record"
    tmp_path = None
    loop = _asyncio.get_running_loop()

    try:
        if needs_file:
            if file is None:
                raise HTTPException(status_code=400, detail="Fichier requis pour cette opération")
            data = await file.read()
            suffix = _os.path.splitext(file.filename or "")[1] or ".mp4"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

        if op == "info":
            res = await loop.run_in_executor(None, lambda: _vm.get_media_info(tmp_path))
            if res.get("error"):
                raise HTTPException(status_code=500, detail=res["error"])
            return {"success": True, **res}

        elif op == "to_gif":
            res = await loop.run_in_executor(None, lambda: _vm.video_to_gif(
                tmp_path, fps=int(fps) if fps else 12, width=width or 480,
                start=start, duration=duration))

        elif op == "gif_to_video":
            res = await loop.run_in_executor(None, lambda: _vm.gif_to_video(
                tmp_path, fps=int(fps) if fps else None))

        elif op == "trim":
            res = await loop.run_in_executor(None, lambda: _vm.video_trim(
                tmp_path, start=start or 0, end=end, duration=duration))

        elif op == "compress":
            res = await loop.run_in_executor(None, lambda: _vm.video_compress(
                tmp_path, crf=crf or 28, scale_width=scale_width))

        elif op == "resize":
            res = await loop.run_in_executor(None, lambda: _vm.video_resize(
                tmp_path, width=width, height=height))

        elif op == "extract_frames":
            res = await loop.run_in_executor(None, lambda: _vm.video_extract_frames(
                tmp_path, fps=fps or 1, max_frames=max_frames or 30))
            if res.get("error"):
                raise HTTPException(status_code=500, detail=res["error"])
            return {"success": True, **res}

        elif op == "speed":
            res = await loop.run_in_executor(None, lambda: _vm.video_speed(
                tmp_path, factor=factor or 2.0))

        elif op == "watermark":
            if not text:
                raise HTTPException(status_code=400, detail="Paramètre 'text' requis pour le filigrane")
            res = await loop.run_in_executor(None, lambda: _vm.video_add_watermark(
                tmp_path, text, position=position or "bottom-right", font_size=font_size or 24))

        elif op == "optimize_gif":
            res = await loop.run_in_executor(None, lambda: _vm.gif_optimize(
                tmp_path, fps=int(fps) if fps else 10, width=width, colors=colors or 128))

        elif op == "screen_record":
            reg = None
            if region:
                try:
                    reg = [int(x) for x in region.split(",")]
                except Exception:
                    reg = None
            res = await loop.run_in_executor(None, lambda: _vm.screen_record_gif(
                duration=min(duration or 5, 20), fps=int(fps) if fps else 10, region=reg))

        else:
            raise HTTPException(status_code=400, detail=f"Opération inconnue : {operation}")

        return _video_edit_result(res)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Génération vidéo LOCALE — CogVideoX / Wan 2.1 (HuggingFace Diffusers)
# ══════════════════════════════════════════════════════════════════════════════

import local_video as _lv


def _video_gen_allowed() -> bool:
    """La génération vidéo locale est-elle autorisée ? Pilotée par le MODE de performance
    (setting video_gen_enabled, calculé selon GPU). Par défaut : suit le support matériel."""
    v = db.get_setting("video_gen_enabled")
    if v is None:
        try:
            return bool(_lv.get_device_info().get("video_gen_supported"))
        except Exception:
            return False
    return bool(v)


def _video_gen_reason() -> str:
    try:
        info = _lv.get_device_info()
    except Exception:
        info = {}
    if not info.get("video_gen_supported"):
        return ("Génération vidéo locale indisponible sur ce matériel "
                f"({info.get('gpu') or info.get('vendor') or 'pas de GPU CUDA'}). "
                "Elle nécessite une carte NVIDIA/CUDA.")
    return ("Génération vidéo locale désactivée dans le mode de performance actuel. "
            "Passe en mode « Performance » ou « Maximum » (Mon jour → Auto-config) pour l'activer.")


@app.get("/api/video/local/models")
async def local_video_models():
    """Retourne les modèles locaux disponibles + infos device (CUDA/CPU/VRAM)."""
    status = _lv.get_models_status()
    if isinstance(status, dict):
        status["video_gen_enabled"] = _video_gen_allowed()
    return status


class LocalVideoTextRequest(BaseModel):
    model_key: str
    prompt: str
    num_steps: int | None = None   # None → défaut du modèle
    num_frames: int | None = None
    fps: int | None = None
    guidance: float | None = None
    duration: float | None = None   # durée cible en secondes (retime + interpolation)
    resolution: int | None = None   # 256 / 384 / 512 (qualité ↔ vitesse)
    seed: int | None = None         # graine (reproductibilité) ; None/-1 = aléatoire
    negative_prompt: str | None = None  # éléments à éviter


@app.post("/api/video/local/generate")
async def local_video_generate_text(body: LocalVideoTextRequest):
    """
    SSE : télécharge le modèle si absent, le charge en mémoire, génère et exporte en MP4.
    Progression : downloading → loading → processing (step N/N) → succeeded/error.
    """
    async def generate():
        import json as _j
        if not _video_gen_allowed():
            yield f"data: {_j.dumps({'status': 'error', 'error': _video_gen_reason()})}\n\n"
            return
        async for event in _lv.generate_video_local_sse(
            model_key=body.model_key,
            prompt=body.prompt,
            num_steps=body.num_steps,
            num_frames=body.num_frames,
            fps=body.fps,
            guidance=body.guidance,
            duration=body.duration,
            resolution=body.resolution,
            seed=body.seed,
            negative_prompt=body.negative_prompt,
        ):
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/video/local/cancel")
async def local_video_cancel():
    """Demande l'annulation de la génération locale en cours (entre deux étapes)."""
    _lv.request_cancel()
    return {"success": True, "message": "Annulation demandée — arrêt à la prochaine étape."}


class PromptEnhanceRequest(BaseModel):
    prompt: str


@app.post("/api/video/enhance-prompt")
async def enhance_video_prompt(body: PromptEnhanceRequest):
    """
    ✨ Améliore un prompt vidéo via le LLM local (Ollama) :
    traduit en anglais (SD1.5 comprend mieux l'anglais) et l'enrichit en
    description cinématographique détaillée → bien meilleure adhérence au texte.
    """
    import httpx as _httpx
    from config import OLLAMA_URL
    raw = (body.prompt or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Prompt vide")

    sys_prompt = (
        "You are a prompt engineer for an AI text-to-video model (Stable Diffusion 1.5 based). "
        "Rewrite the user's idea into ONE single rich English prompt, optimized for video generation. "
        "Rules: translate to English; keep the user's subject and intent EXACTLY; add concrete visual "
        "details (lighting, camera angle, environment, mood, colors, style like 'cinematic, 4k, detailed'); "
        "describe motion suitable for a short clip; NO preamble, NO quotes, NO explanations, NO line breaks. "
        "Output ONLY the final prompt, under 60 words."
    )
    # Modèle rapide pour cette tâche courte
    candidates = ["qwen2.5:3b", "llama3.2:3b", "qwen2.5:7b", "hermes3:8b"]
    model = None
    try:
        async with _httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            avail = [m["name"] for m in r.json().get("models", [])] if r.status_code == 200 else []
        model = next((m for m in candidates if m in avail), (avail[0] if avail else None))
    except Exception:
        pass
    if not model:
        raise HTTPException(status_code=503, detail="Ollama indisponible pour l'amélioration du prompt")

    try:
        async with _httpx.AsyncClient(timeout=40.0) as c:
            resp = await c.post(f"{OLLAMA_URL}/api/chat", json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": raw},
                ],
                "stream": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.7, "num_predict": 160},
            })
        data = resp.json()
        enhanced = (data.get("message", {}) or {}).get("content", "").strip()
        # Nettoyage : retire guillemets/sauts de ligne éventuels
        enhanced = enhanced.strip().strip('"').strip("'").replace("\n", " ").strip()
        if not enhanced:
            raise ValueError("réponse vide")
        return {"success": True, "original": raw, "enhanced": enhanced, "model": model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Échec de l'amélioration : {e}")


@app.post("/api/video/local/generate/image")
async def local_video_generate_image(
    model_key: str = Form(...),
    prompt: str = Form(""),
    num_steps: int | None = Form(None),   # None → défaut du modèle
    image: UploadFile = File(...),
):
    """SSE : génération image-to-video locale (CogVideoX-5B-I2V)."""
    import tempfile

    img_bytes = await image.read()
    ext = ".jpg"
    if image.content_type:
        if "png"  in image.content_type: ext = ".png"
        elif "webp" in image.content_type: ext = ".webp"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(img_bytes)
        tmp_path = tmp.name

    async def generate():
        import json as _j
        if not _video_gen_allowed():
            yield f"data: {_j.dumps({'status': 'error', 'error': _video_gen_reason()})}\n\n"
            return
        try:
            async for event in _lv.generate_video_local_sse(
                model_key=model_key,
                prompt=prompt,
                num_steps=num_steps,
                image_path=tmp_path,
            ):
                yield event
        finally:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Voix — Text-to-Speech (Edge-TTS neural voices, gratuit, sans clé API)
# ══════════════════════════════════════════════════════════════════════════════

# Voix françaises recommandées (toutes neurales, gratuites)
# ══════════════════════════════════════════════════════════════════════════════
# Devis / Facturation IT
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Agent IA Documentation Technique
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# v2.30.0 — Operations Safety : routes REST
# ══════════════════════════════════════════════════════════════════════════════

# ── Pre/Post-Check ──
# ── Command Safety ──
# ── Client Health Score ── (NB: /api/client-health pour éviter collision avec /api/health système)
# ══════════════════════════════════════════════════════════════════════════════
# Santé
# ══════════════════════════════════════════════════════════════════════════════
