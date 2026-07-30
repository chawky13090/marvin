"""Composition root FastAPI de Marvin.

Lancement :
    uvicorn main:app --host 127.0.0.1 --port 8005

Ne pas utiliser ``--reload`` : il interrompt les flux SSE pendant les changements.
L'historique détaillé des versions est conservé dans ``DEVELOPMENT-JOURNAL.md`` et Git.
"""

# v2.500 — SearXNG multi-moteurs et rechargement vérifié
# v2.499 — projets et conversations pilotables depuis le chat
# v2.498 — audit outils, fiabilité runtime et recherche SearXNG pertinente
# v2.497 — ouverture Windows, navigation PC et projection PDF fiabilisées
# v2.486 — Research Engine v3 adaptatif, vérifiable et réversible
# v2.485 — vocalisation fiable des réponses Cloud answer_final
# v2.484 — barre contextuelle stable et accueil orienté travail
# v2.483 — navigation adaptative Focus, Rail, Complet et rollback Classique
# v2.482 — recherche Web cohérente et palette de commandes React fiabilisée
# v2.481 — fermeture des listeners HTTP LAN derrière la passerelle HTTPS
# v2.480 — passerelle HTTPS LAN, autorité locale et jumelage à usage unique
# v2.479 — activation vocale explicite, dock inférieur et retry TTS borné
# v2.478 — Quiet Workbench, accueil contextuel et historique unifié
# v2.476 — SearXNG prioritaire, recherche profonde multi-passes et routeur de capacités
# v2.475 — contrats Web explicites et refus des promesses d'outils non exécutées
# v2.474 — sidebar conversations accessible, archivage réversible et exports
# v2.468 — métriques bornées des décisions d'accès et d'idempotence
# v2.467 — clés d'idempotence HTTP sur les gateways d'outils UI et MCP
# v2.466 — autorisation LAN par capacités et profils d'appareil
# v2.465 — identité LAN signée, jumelage, CSRF et WebSocket protégés
# v2.464 — inventaire OpenAPI exhaustif et gate contractuel par famille
# v2.463 — réplication chiffrée hors stockage, idempotente et vérifiée
# v2.462 — restauration globale hors ligne compensée et projections réconciliées
# v2.461 — bundle global chiffré et restauration isolée vérifiée
# v2.460 — fraîcheur factuelle et restauration mémoire compensée
# v2.489 — citations Research cliquables et bandeau Chat compact unifié
# v2.488 — Research universel visible et suivis référentiels vérifiables
# v2.487 — recherche profonde contextuelle, seuils mesurables et façade v3 unifiée
# v2.458 — politique de données modèles exhaustive et privée par défaut
# v2.457 — Code Workspace E2E natif, réparation ciblée et artefact préservé
# v2.456 — corrélation HTTP, Runner, outils et preuves persistées
# v2.455 — découverte dynamique des capacités des modèles locaux
# v2.454 — apprentissage durable avec SQLite autoritatif
# v2.453 — cohérence, provenance et conflits du Memory Mesh
# v2.452 — transitions de confidentialité durables dans Coding Mission
# v2.451 — provenance générative documents, e-mails et Code Workspace
# v2.449 — matrice confidentialité/modèles et provenance du profil effectif
# v2.448 — zéro consommateur direct, outils système conditionnels et Council sous harness
# v2.447 — contenu et documents sous harness, téléchargement confiné
# v2.446 — API et workers e-mail sous harness, erreurs bornées et rejeu stable
# v2.445 — multi-agents, workflows et cron sous harness commun
# Les versions antérieures restent documentées dans Git et DEVELOPMENT-JOURNAL.md.

from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import bug_log
from api_observability import ApiObservabilityMiddleware
from api_contract_schema import install_access_contract
import chat_turn_runtime
import generation_runtime
import web_runtime
from agent import _refresh_model_cache
from api.agent_gateway import router as agent_gateway_router
from api.avatar import router as avatar_router
from api.backups import router as backups_router
from api.billing import router as billing_router
from api.calendar import router as calendar_router
from api.coding import router as coding_router
from api.connections import router as connections_router
from api.content import router as content_router
from api.conversations import router as conversations_router
from api.cortex import router as cortex_router
from api.cron_monitor import router as cron_monitor_router
from api.diagnostics import router as diagnostics_router
from api.doctor import router as doctor_router
from api.documents import router as documents_router
from api.email_accounts import router as email_accounts_router
from api.email_automation import router as email_automation_router
from api.email_mailbox import router as email_mailbox_router
from api.email_preferences import router as email_preferences_router
from api.evolution import router as evolution_router
from api.forge import router as forge_router
from api.health import router as health_router
from api.history import router as history_router
from api.knowledge import router as knowledge_router
from api.lan_access import router as lan_access_router
from api.memories import router as memories_router
from api.missions import router as missions_router
from api.model_market import router as model_market_router
from api.model_selection import router as model_selection_router
from api.multi_agents import router as multi_agents_router
from api.notes import router as notes_router
from api.operations import router as operations_router
from api.proactive import router as proactive_router
from api.projects import router as projects_router
from api.runtime_config import router as runtime_config_router
from api.settings import router as settings_router
from api.skills import router as skills_router
from api.ssh import router as ssh_router
from api.storage import router as storage_router
from api.system_tools import router as system_tools_router
from api.tasks import router as tasks_router
from api.technical_docs import router as technical_docs_router
from api.templates import router as templates_router
from api.video_editing import router as video_editing_router
from api.video_local import router as video_local_router
from api.video_remote import router as video_remote_router
from api.vm_lab import router as vm_lab_router
from api.voice import prewarm_whisper
from api.voice import router as voice_router
from api.workflows import router as workflows_router
from app_version import APP_VERSION
from communication_workers import (
    calendar_sync_worker as _calendar_sync_worker,
    email_automation_worker as _email_automation_worker,
    email_watch_worker as _email_watch_worker,
    event_reminder_worker as _event_reminder_worker,
)
from config import FRONTEND_URL
from cron_runtime import cron_worker as _cron_worker
from proactive_service import proactive_worker as _proactive_worker
from runtime_supervisor import RuntimeSupervisor
from runtime_workers import (
    build_tool_index as _build_tool_index,
    database_backup_worker as _db_backup_worker,
    health_trend_worker as _health_trend_worker,
    memory_consolidation_worker as _memory_consolidation_worker,
    prewarm_default_models as _prewarm_default_model,
    skill_night_learning_worker as _skill_night_learning_worker,
)
from lan_access import LanAccessMiddleware


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, OSError):
        pass


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Initialise les dépendances partagées et supervise les workers de Marvin."""
    print(
        "[Marvin] Accès LAN protégé. Code visible dans "
        "Paramètres > Connexions sur le PC principal."
    )
    chat_turn_runtime.recover_orphaned_turns()
    chat_turn_runtime.prune()
    try:
        import auto_config

        auto_result = await auto_config.apply_auto_config()
        if auto_result.get("enabled"):
            hardware = auto_result["hardware"]
            print(
                "[Marvin] Auto-config : "
                f"{hardware['gpu']} ({hardware['vram_gb']} Go) -> {auto_result['applied']}"
            )
    except Exception as exc:
        bug_log.log_bug(
            "startup_auto_config",
            type(exc).__name__,
            context={"exception_type": type(exc).__name__},
        )
        print("[Marvin] Auto-config indisponible; configuration existante conservée.")

    await _refresh_model_cache()

    import coding_jobs
    import engineering_radar
    import model_market

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
        supervisor.start("cloud-model-fleet", model_market.sync_recommended_cloud_models)
        supervisor.start("engineering-radar", engineering_radar.background_worker)
        try:
            coding_jobs.start_pending()
            coding_jobs_started = True
        except coding_jobs.CodingJobStoreError as exc:
            bug_log.log_bug(
                "startup_coding_jobs",
                type(exc).__name__,
                context={"exception_type": type(exc).__name__},
            )
        try:
            import skills

            skills.seed_examples()
        except Exception as exc:
            bug_log.log_bug(
                "startup_skill_seed",
                type(exc).__name__,
                context={"exception_type": type(exc).__name__},
            )
        yield
    finally:
        await chat_turn_runtime.shutdown()
        if coding_jobs_started:
            await coding_jobs.shutdown()
        try:
            import local_model_installer

            await local_model_installer.shutdown()
        except Exception as exc:
            bug_log.log_bug(
                "shutdown_local_model_installer",
                type(exc).__name__,
                context={"exception_type": type(exc).__name__},
            )
        await supervisor.shutdown()
        try:
            import web_browser

            await web_browser.close()
        except Exception as exc:
            bug_log.log_bug(
                "shutdown_web_browser",
                type(exc).__name__,
                context={"exception_type": type(exc).__name__},
            )
        await generation_runtime.close()
        await web_runtime.close()


app = FastAPI(
    title="Marvin — Assistance Informatique",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(LanAccessMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8005",
        "http://127.0.0.1:8005",
    ],
    allow_origin_regex=(
        r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):\d+"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiObservabilityMiddleware)

app.include_router(doctor_router)
app.include_router(cortex_router)
app.include_router(forge_router)
app.include_router(evolution_router)
app.include_router(missions_router)
app.include_router(model_market_router)
app.include_router(knowledge_router)
app.include_router(lan_access_router)
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
app.include_router(video_editing_router)
app.include_router(video_local_router)
app.include_router(video_remote_router)
app.include_router(runtime_config_router)
app.include_router(skills_router)
app.include_router(content_router)
app.include_router(connections_router)
app.include_router(email_accounts_router)
app.include_router(email_mailbox_router)
app.include_router(email_preferences_router)
app.include_router(email_automation_router)
app.include_router(cron_monitor_router)
app.include_router(ssh_router)
app.include_router(storage_router)
app.include_router(health_router)
app.include_router(agent_gateway_router)
app.include_router(model_selection_router)
app.include_router(proactive_router)
install_access_contract(app)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    incident_id = uuid.uuid4().hex
    request_id = str(getattr(request.state, "request_id", "") or uuid.uuid4().hex)
    bug_log.log_bug(
        "http_exception",
        type(exc).__name__,
        context={
            "path": str(request.url.path)[:500],
            "method": str(request.method)[:16],
            "incident_id": incident_id,
            "request_id": request_id,
            "exception_type": type(exc).__name__[:160],
        },
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Une erreur interne est survenue.",
            "incident_id": incident_id,
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )
