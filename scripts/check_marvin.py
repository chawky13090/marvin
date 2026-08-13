"""Orchestrateur des controles reproductibles de Marvin.

Ce script ne démarre jamais FastAPI ni Qdrant dans un second processus. Les contrôles
live passent exclusivement par HTTP afin de ne pas ouvrir Qdrant hors de FastAPI.
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from repository_test_scope import backend_python_files


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VENV_PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"
EXPECTED_STAGE_COUNT = 314


@dataclass(frozen=True)
class Stage:
    name: str
    command: tuple[str, ...] | None = None
    action: str | None = None
    timeout_seconds: int = 180
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        if not 10 <= self.timeout_seconds <= 900:
            raise ValueError("Le timeout d'une étape doit être compris entre 10 et 900 s.")


@dataclass(frozen=True)
class StageResult:
    name: str
    success: bool
    duration_seconds: float
    skipped: bool = False
    reason: str | None = None


def npm_command() -> str:
    command = shutil.which("npm.cmd") or shutil.which("npm")
    if not command:
        raise RuntimeError("npm est introuvable dans PATH.")
    return command


def compile_backend() -> None:
    files = backend_python_files(BACKEND)
    for path in files:
        py_compile.compile(str(path), doraise=True)
    print(f"Compilation Python OK - {len(files)} fichiers.")


def run_stage(stage: Stage) -> tuple[bool, float]:
    print(f"\n{'=' * 68}\n{stage.name}\n{'=' * 68}", flush=True)
    started = time.perf_counter()
    try:
        if stage.action == "compile_backend":
            compile_backend()
            return True, time.perf_counter() - started
        if not stage.command:
            raise RuntimeError("Etape sans commande.")
        completed = subprocess.run(
            stage.command,
            cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            check=False,
            timeout=stage.timeout_seconds,
        )
        return completed.returncode == 0, time.perf_counter() - started
    except subprocess.TimeoutExpired:
        print(
            f"ECHEC: étape interrompue après {stage.timeout_seconds} secondes.",
            file=sys.stderr,
        )
        return False, time.perf_counter() - started
    except (OSError, RuntimeError, py_compile.PyCompileError) as exc:
        print(f"ECHEC: {exc}", file=sys.stderr)
        return False, time.perf_counter() - started


def execute_stages(selected: list[Stage], *, fail_fast: bool) -> list[StageResult]:
    results: list[StageResult] = []
    for stage in selected:
        if stage.skip_reason:
            print(f"[SKIP] {stage.name}: {stage.skip_reason}", flush=True)
            results.append(StageResult(stage.name, True, 0.0, True, stage.skip_reason))
            continue
        success, duration = run_stage(stage)
        results.append(StageResult(stage.name, success, duration))
        if fail_fast and not success:
            break
    return results


def write_report(
    results: list[StageResult],
    *,
    expected_count: int,
    quick: bool,
    live: bool,
    fail_fast: bool,
    output_path: Path,
) -> None:
    artifacts_root = (ROOT / "artifacts").resolve()
    resolved = output_path.resolve()
    try:
        resolved.relative_to(artifacts_root)
    except ValueError as exc:
        raise ValueError("Le rapport doit rester sous artifacts/.") from exc
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": {"quick": quick, "live": live, "fail_fast": fail_fast},
        "expected_stages": expected_count,
        "executed_stages": sum(not item.skipped for item in results),
        "skipped": sum(item.skipped for item in results),
        "succeeded": sum(item.success and not item.skipped for item in results),
        "failed": sum(not item.success and not item.skipped for item in results),
        "success": bool(results) and len(results) == expected_count and all(item.success for item in results),
        "stages": [
            {
                "name": item.name,
                "status": "skipped" if item.skipped else ("passed" if item.success else "failed"),
                "duration_seconds": round(item.duration_seconds, 3),
                "reason": item.reason,
            }
            for item in results
        ],
    }
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(resolved.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(resolved)


def stages(*, quick: bool, live: bool) -> list[Stage]:
    if not VENV_PYTHON.exists():
        raise RuntimeError("backend/.venv est absent. Lancez INSTALLER-NOUVEAU-PC.bat.")

    python = str(VENV_PYTHON)
    npm = npm_command()
    result = [
        Stage("Provenance du runtime Python", (python, "scripts/test_python_runtime.py")),
        Stage("Runner de tests exhaustif", (python, "scripts/test_check_marvin_runner.py")),
        Stage("Runtime Node et modules natifs", ("node", "scripts/check_runtime.mjs")),
        Stage("Superviseur du backend Windows", (python, "scripts/test_server_supervisor.py")),
        Stage("Arrêt borné du backend", (python, "scripts/test_shutdown_runtime.py")),
        Stage("Fermeture explicite de Qdrant", (python, "scripts/test_vector_store_lifecycle.py")),
        Stage("Boucle réseau résiliente du backend Windows", (python, "scripts/test_windows_event_loop.py")),
        Stage("Installation Windows portable", (python, "scripts/test_installer_contract.py")),
        Stage("ACL Windows des données Marvin", (python, "scripts/test_data_acl.py")),
        Stage("Sauvegarde globale chiffrée", (python, "scripts/test_full_backup.py")),
        Stage(
            "Restauration globale compensée",
            (python, "scripts/test_full_backup_recovery.py"),
        ),
        Stage(
            "Réplication vérifiée des sauvegardes",
            (python, "scripts/test_backup_replication.py"),
        ),
        Stage(
            "Sauvegarde portable sans secrets DPAPI",
            (python, "scripts/test_portable_backup.py"),
        ),
        Stage("Activation locale de l'avatar", (python, "scripts/test_avatar_api.py")),
        Stage("Invariants d'architecture", (python, "scripts/check_architecture.py")),
        Stage(
            "Inventaire contractuel OpenAPI",
            (python, "scripts/test_api_contract_inventory.py"),
        ),
        Stage(
            "Contrat de consolidation globale",
            (python, "scripts/test_frontier_consolidation_contract.py"),
        ),
        Stage("Journalisation structurée et bornée", (python, "scripts/test_structured_logging.py")),
        Stage("Corrélation et métriques HTTP", (python, "scripts/test_api_observability.py")),
        Stage("SLO roulant et budget d'erreur", (python, "scripts/test_runtime_slo.py")),
        Stage("Inventaire des consommateurs d'outils", (python, "scripts/test_tool_consumer_inventory.py")),
        Stage("Disponibilite reseau des 364 outils", (python, "scripts/test_tool_availability.py")),
        Stage("Inventaire E0-E7 des outils", (python, "scripts/test_tool_evidence_inventory.py")),
        Stage("Pré-inscription de la campagne B", (python, "scripts/test_tool_evidence_campaign_b.py")),
        Stage("Gel de la taxonomie E7 R/C/I/N/P", (python, "scripts/test_e7_taxonomy_freeze.py")),
        Stage("Preregistration E7 apply reversible supersédée", (python, "scripts/test_e7_bulk_rename_central_store_preregistration.py")),
        Stage("Runner E7 apply historique préservé", (python, "scripts/test_e7_bulk_rename_central_store_preregistration.py")),
        Stage("Registre de sécurité réévalué", (python, "scripts/test_security_register_contract.py")),
        Stage("Analyse statique des 22 surfaces E7", (python, "scripts/test_e7_surface_analysis_result.py")),
        Stage("Analyse E7 v1.4 sensible aux chemins", (python, "scripts/test_e7_path_surface_result.py")),
        Stage(
            "Pré-enregistrement TD-014 multi-magasins",
            (python, "scripts/test_multistore_correction_preregistration.py"),
        ),
        Stage(
            "Branches TD-014 resume et cancel",
            (python, "scripts/test_td014_action_surfaces.py"),
        ),
        Stage(
            "Supersession TD-014 sans promotion E7",
            (python, "scripts/test_multistore_correction_assessment.py"),
        ),
        Stage(
            "Erratum TD-014 avant rejeu runtime",
            (python, "scripts/test_multistore_assessment_erratum.py"),
        ),
        Stage(
            "Résultat runtime TD-014 sans promotion E7",
            (python, "scripts/test_multistore_runtime_result.py"),
        ),
        Stage(
            "Pré-enregistrement de l'ablation des outils",
            (python, "scripts/test_tool_selection_ablation_preregistration.py"),
        ),
        Stage("Résultat E7 apply immuable et verrouillé", (python, "scripts/test_e7_apply_execution_result.py")),
        Stage("Stockage central des rollbacks bulk rename", (python, "scripts/test_bulk_rename_rollback_store.py")),
        Stage("Appareil gelé du rejeu E7 apply v1.2", (python, "scripts/test_e7_apply_replay_freeze_post_result_v12.py")),
        Stage("Résultat du rejeu E7 apply v1.2", (python, "scripts/test_e7_apply_replay_result_v12.py")),
        Stage("Gel des strates E7 et du harnais H7", (python, "scripts/test_h7_fixture_strategy.py")),
        Stage("Gel des 22 contrats de fixtures E7", (python, "scripts/test_direct_fixture_contracts.py")),
        Stage("Harnais isolé des six fixtures E7", (python, "scripts/test_e7_fixture_harness.py")),
        Stage("Implémentations des six fixtures E7", (python, "scripts/test_e7_fixture_implementations.py")),
        Stage("Readiness de démarrage prouvée", (python, "scripts/test_startup_readiness_contract.py")),
        Stage("Clôture reproductible de TD-015", (python, "scripts/test_td015_closure_contract.py")),
        Stage("Portabilité inter-OS des preuves", (python, "scripts/test_evidence_portability.py")),
        Stage("Qualification des environnements pilotes E7", (python, "scripts/test_e7_environment_qualification.py")),
        Stage("Routes de lecture bloquantes externalisées", (python, "scripts/test_nonblocking_read_routes.py")),
        Stage("Isolation des ressources temporaires des smokes", (python, "scripts/test_smoke_resource_isolation.py")),
        Stage("Pilote E7 preview historique préservé", (python, "scripts/test_e7_bulk_rename_central_store_preregistration.py")),
        Stage("Extraction privée des demandes réelles", (python, "scripts/test_real_usage_corpus.py")),
        Stage("Inventaire des données personnelles", (python, "scripts/test_privacy_inventory.py")),
        Stage("Export chiffré des données personnelles", (python, "scripts/test_privacy_rights.py")),
        Stage("Runtime commun des outils", (python, "scripts/test_tool_runtime.py")),
        Stage("Gateway des routes agenda", (python, "scripts/test_calendar_gateway_api.py")),
        Stage("Gateway des orchestrateurs", (python, "scripts/test_orchestration_tool_gateway.py")),
        Stage("Gateway contenu et documents", (python, "scripts/test_content_document_gateway.py")),
        Stage("Gateway des outils système", (python, "scripts/test_system_tools_gateway.py")),
        Stage("Erreurs API expurgées", (python, "scripts/test_api_errors.py")),
        Stage("Diagnostic privé du matching des skills", (python, "scripts/test_skill_match_logging.py")),
        Stage("Inventaire des persistances JSONL", (python, "scripts/test_persistence_inventory.py")),
        Stage("Registre durable de preuves métier", (python, "scripts/test_durable_evidence_store.py")),
        Stage("Intégrité des preuves Marvin Forge", (python, "scripts/test_forge_evidence.py")),
        Stage("Coffre DPAPI des identifiants globaux", (python, "scripts/test_credentials_vault.py")),
        Stage("Cycle de vie et portabilité des secrets", (python, "scripts/test_secret_lifecycle.py")),
        Stage(
            "Coffre DPAPI du compte de service Google",
            (python, "scripts/test_google_service_account_vault.py"),
        ),
        Stage(
            "API du compte de service Google",
            (python, "scripts/test_google_service_account_api.py"),
        ),
        Stage(
            "Coffre DPAPI des comptes e-mail",
            (python, "scripts/test_email_account_vault.py"),
        ),
        Stage(
            "Migration OAuth SQLite vers DPAPI",
            (python, "scripts/test_oauth_legacy_migration.py"),
        ),
        Stage("API Chat, outils et MCP extraite", (python, "scripts/test_agent_gateway_api.py")),
        Stage(
            "Frontière du serveur MCP",
            (python, "scripts/test_mcp_server_boundary.py"),
        ),
        Stage(
            "API modèles et proactive extraite",
            (python, "scripts/test_model_proactive_api.py"),
        ),
        Stage(
            "Composition FastAPI minimale",
            (python, "scripts/test_main_composition.py"),
        ),
        Stage("Superviseur idempotent des workers", (python, "scripts/test_runtime_supervisor.py")),
        Stage("Workers de maintenance extraits", (python, "scripts/test_runtime_workers.py")),
        Stage("Workers e-mail et agenda extraits", (python, "scripts/test_communication_workers.py")),
        Stage("Service proactif et voix du briefing", (python, "scripts/test_proactive_service.py")),
        Stage("Briefing proactif concurrent", (python, "scripts/test_proactive_briefing.py")),
        Stage("Moteur cron et reprises longues", (python, "scripts/test_cron_runtime.py")),
        Stage("Migrations SQLite transactionnelles", (python, "scripts/test_db_migrations.py")),
        Stage("Composition déterministe de SQLite", (python, "scripts/test_database_bootstrap.py")),
        Stage(
            "Maintenance SQLite hors ligne et compensable",
            (python, "scripts/test_sqlite_maintenance.py"),
        ),
        Stage(
            "Frontière de persistance unique FastAPI",
            ("node", "--no-warnings", "scripts/test_frontend_persistence_boundary.mjs"),
        ),
        Stage("Repository conversations et messages", (python, "scripts/test_conversation_repository.py")),
        Stage("Repository des connexions SSH", (python, "scripts/test_ssh_connection_repository.py")),
        Stage("Repository des workflows", (python, "scripts/test_workflow_repository.py")),
        Stage("Repository des paramètres", (python, "scripts/test_settings_repository.py")),
        Stage("API bornée des paramètres", (python, "scripts/test_settings_api.py")),
        Stage(
            "Repositories mémoires, tâches et notes",
            (python, "scripts/test_personal_data_repositories.py"),
        ),
        Stage("Repository des événements", (python, "scripts/test_event_repository.py")),
        Stage(
            "Repositories projets et artefacts",
            (python, "scripts/test_project_artifact_repositories.py"),
        ),
        Stage(
            "Organisation des projets et conversations depuis le chat",
            (python, "scripts/test_workspace_organization.py"),
        ),
        Stage(
            "Repository des exécutions et de la fiabilité",
            (python, "scripts/test_execution_repository.py"),
        ),
        Stage(
            "Repositories de l'état opérationnel",
            (python, "scripts/test_operational_state_repositories.py"),
        ),
        Stage(
            "Repository de facturation",
            (python, "scripts/test_billing_repository.py"),
        ),
        Stage(
            "Repository des contrôles opérationnels",
            (python, "scripts/test_operations_repository.py"),
        ),
        Stage(
            "Repository de documentation technique",
            (python, "scripts/test_documentation_repository.py"),
        ),
        Stage(
            "Documentation canonique et dette explicite",
            (python, "scripts/test_documentation_baseline.py"),
        ),
        Stage(
            "Repository de santé client",
            (python, "scripts/test_client_health_repository.py"),
        ),
        Stage(
            "Repository de sécurité des commandes",
            (python, "scripts/test_command_safety_repository.py"),
        ),
        Stage(
            "Approbations d'outils et autonomie temporaire",
            (python, "scripts/test_tool_approval_flow.py"),
        ),
        Stage(
            "Cycle de vie UI des approbations",
            ("node", "scripts/test_approval_lifecycle_ui.mjs"),
        ),
        Stage(
            "Reprise UI après approbation",
            ("node", "scripts/test_approval_continuation.mjs"),
        ),
        Stage(
            "Repository des fiches de révision",
            (python, "scripts/test_flashcard_repository.py"),
        ),
        Stage(
            "Repository de connaissances IT",
            (python, "scripts/test_it_knowledge_repository.py"),
        ),
        Stage(
            "Sauvegarde et restauration SQLite",
            (python, "scripts/test_backup_service.py"),
        ),
        Stage(
            "Migration chiffrée et rollback des sauvegardes",
            (python, "scripts/test_backup_migration.py"),
        ),
        Stage("Fermeture garantie des connexions SQLite", (python, "scripts/test_db_connection_hygiene.py")),
        Stage("Politiques textuelles de l'agent", (python, "scripts/test_agent_policy.py")),
        Stage("Sécurité déterministe de l'agent", (python, "scripts/test_agent_safety.py")),
        Stage("Protocole messages Ollama et SSE", (python, "scripts/test_agent_protocol.py")),
        Stage("Transport HTTP et JSONL Ollama", (python, "scripts/test_agent_transport.py")),
        Stage("Runtime partagé des générations", (python, "scripts/test_generation_runtime.py")),
        Stage("Politique dynamique des modèles locaux", (python, "scripts/test_local_model_policy.py")),
        Stage("Qualification runtime des modèles locaux", (python, "scripts/test_local_model_qualification.py")),
        Stage("Portefeuille autonome des modèles locaux", (python, "scripts/test_local_model_portfolio.py")),
        Stage("API du portefeuille autonome", (python, "scripts/test_local_model_portfolio_api.py")),
        Stage("Installation contrôlée des modèles locaux", (python, "scripts/test_local_model_installer.py")),
        Stage("Plan modèles locaux de l'installateur", (python, "scripts/test_install_model_plan.py")),
        Stage("Routage des profils et modeles", (python, "scripts/test_agent_routing.py")),
        Stage("Construction du prompt systeme", (python, "scripts/test_agent_prompt.py")),
        Stage("Selection bornee des outils LLM", (python, "scripts/test_agent_tool_selection.py")),
        Stage("Façade d'orchestration commutable", (python, "scripts/test_agent_orchestration.py")),
        Stage("Policy Engine contextuel", (python, "scripts/test_policy_engine.py")),
        Stage(
            "Frontiere web non fiable et bornes du mode auto",
            (python, "scripts/test_untrusted_web_and_autonomy.py"),
        ),
        Stage(
            "Garde-fous de la consolidation de competences",
            (python, "scripts/test_skill_consolidation_guards.py"),
        ),
        Stage(
            "Commandes sensibles confirmees malgre l autonomie",
            (python, "scripts/test_sensitive_command_confirmation.py"),
        ),
        Stage(
            "Suppression de fichier vers la Corbeille",
            (python, "scripts/test_file_delete_trash.py"),
        ),
        Stage(
            "Repli local de continuite sur panne Cloud",
            (python, "scripts/test_connectivity_resilience.py"),
        ),
        Stage(
            "Veille du catalogue de modeles Cloud",
            (python, "scripts/test_model_catalog_watch.py"),
        ),
        Stage(
            "Peripheriques Windows (imprimantes, USB, Bluetooth)",
            (python, "scripts/test_tool_domain_windows_devices.py"),
        ),
        Stage(
            "Lot d'outils parallele (concurrence bornee)",
            (python, "scripts/test_agent_tool_batch_parallel.py"),
        ),
        Stage(
            "Reparation des parametres array/object serialises en chaine",
            (python, "scripts/test_stringified_array_repair.py"),
        ),
        Stage("Catalogue dynamique des capacités", (python, "scripts/test_capability_catalog.py")),
        Stage("Découverte enrichie des capacités", (python, "scripts/test_capability_discovery_v2.py")),
        Stage("Boucle agentique LLM native", (python, "scripts/test_native_agent_runtime.py")),
        Stage("Chemin natif du Runner", (python, "scripts/test_native_agent_path.py")),
        Stage("Execution deterministe des outils LLM", (python, "scripts/test_agent_execution.py")),
        Stage("Redecouverte bornee des outils inconnus", (python, "scripts/test_unknown_tool_rediscovery.py")),
        Stage("Independance de Forge v1.2", (python, "scripts/test_forge_v12_contract.py")),
        Stage("Préparation des étapes d'outils", (python, "scripts/test_agent_tool_step.py")),
        Stage("Politique de dispatch des outils", (python, "scripts/test_agent_tool_dispatch.py")),
        Stage("Post-validation des résultats d'outils", (python, "scripts/test_agent_tool_postprocess.py")),
        Stage("Finalisation idempotente des compétences", (python, "scripts/test_agent_skill_outcome.py")),
        Stage("Escalade Council après désaccord", (python, "scripts/test_agent_council_escalation.py")),
        Stage("Apprentissage post-réponse suivi", (python, "scripts/test_agent_learning.py")),
        Stage("Préparation déterministe du contexte de tour", (python, "scripts/test_agent_turn_context.py")),
        Stage("Enrichissements concurrents du tour", (python, "scripts/test_agent_enrichment.py")),
        Stage("Contexte prompt des compétences", (python, "scripts/test_agent_skill_context.py")),
        Stage("Itération modèle typée", (python, "scripts/test_agent_model_step.py")),
        Stage("Lot d'outils observé et persistant", (python, "scripts/test_agent_tool_batch.py")),
        Stage("Historique de chat serveur autoritatif", (python, "scripts/test_server_authoritative_history.py")),
        Stage("Pagination UI des conversations", ("node", "scripts/test_conversation_paging_ui.mjs")),
        Stage("Finalisation commune du tour", (python, "scripts/test_agent_turn_completion.py")),
        Stage("Politiques et budget du Runner", (python, "scripts/test_agent_loop_policy.py")),
        Stage("Revue indépendante des réponses et actions", (python, "scripts/test_agent_review.py")),
        Stage("Contexte de session et captures", (python, "scripts/test_agent_context.py")),
        Stage("Préparation durable d'un tour", (python, "scripts/test_agent_session.py")),
        Stage("Compilation du plan de tour", (python, "scripts/test_agent_planning.py")),
        Stage("Matérialisation des outils obligatoires", (python, "scripts/test_agent_required_tools.py")),
        Stage("Configuration modèle et confidentialité", (python, "scripts/test_agent_model_config.py")),
        Stage("Contexte Ollama réellement prouvé", (python, "scripts/test_ollama_context_runtime.py")),
        Stage("Admission Ollama et verrou Forge", (python, "scripts/test_ollama_context_admission.py")),
        Stage("Verrou Forge Cloud exact", (python, "scripts/test_forge_cloud_runtime_lock.py")),
        Stage(
            "Contrat Forge Windows Operator",
            (python, "scripts/test_windows_operator_benchmark_contract.py"),
        ),
        Stage(
            "Corpus Forge Windows gele",
            (python, "scripts/test_windows_operator_corpus.py"),
        ),
        Stage(
            "Decision Forge Windows mecanique",
            (python, "scripts/test_windows_operator_acceptance.py"),
        ),
        Stage(
            "Rectificatif du routage Forge Windows",
            (python, "scripts/test_windows_routing_rectification.py"),
        ),
        Stage(
            "Operateur Windows type et postconditions",
            (python, "scripts/test_windows_task.py"),
        ),
        Stage(
            "Matrice des profils de confidentialité",
            (python, "scripts/test_privacy_model_matrix.py"),
        ),
        Stage(
            "Matrice de pannes des quatre profils",
            (python, "scripts/test_privacy_failure_matrix.py"),
        ),
        Stage("État observable du Runner", (python, "scripts/test_agent_runner.py")),
        Stage("Observabilité du Runner", (python, "scripts/test_agent_observability.py")),
        Stage("Finalisation commune du Runner", (python, "scripts/test_agent_finalization.py")),
        Stage("Recus idempotents des actions chat", (python, "scripts/test_action_replay.py")),
        Stage("Tours chat durables et detachables", (python, "scripts/test_chat_turn_runtime.py")),
        Stage("Reconnexion SSE du frontend", ("node", "--no-warnings", "scripts/test_chat_stream.mjs")),
        Stage("Reprise des lectures backend frontend", ("node", "scripts/test_backend_read.mjs")),
        Stage("Repli frontend des conversations volumineuses", ("node", "scripts/test_backend_fallback.mjs")),
        Stage("Normalisation des listes de conversations", ("node", "scripts/test_conversation_payload.mjs")),
        Stage("Résilience du rafraîchissement des conversations", ("node", "scripts/test_workspace_refresh.mjs")),
        Stage("Domaine d'outils Fichiers", (python, "scripts/test_tool_domain_filesystem.py")),
        Stage("Formatage documentaire partagé", (python, "scripts/test_document_formatting.py")),
        Stage("Profil et modèles documentaires", (python, "scripts/test_document_profile.py")),
        Stage("Domaine DOCX et conversions", (python, "scripts/test_tool_domain_documents.py")),
        Stage("PowerPoint et extraction DOCX", (python, "scripts/test_tool_domain_office_documents.py")),
        Stage("Domaine archives", (python, "scripts/test_tool_domain_archives.py")),
        Stage("Domaine tableurs", (python, "scripts/test_tool_domain_spreadsheets.py")),
        Stage("Domaine OCR", (python, "scripts/test_tool_domain_ocr.py")),
        Stage("Domaine captures documentaires", (python, "scripts/test_tool_domain_screenshots.py")),
        Stage("OCR écran borné", (python, "scripts/test_tool_domain_screen_ocr.py")),
        Stage("Transcription Whisper partagée", (python, "scripts/test_voice_transcription.py")),
        Stage("Domaine images", (python, "scripts/test_tool_domain_images.py")),
        Stage("Graphiques PNG déterministes", (python, "scripts/test_tool_domain_charts.py")),
        Stage("Noyau PDF", (python, "scripts/test_tool_domain_pdf_core.py")),
        Stage("PDF avancé", (python, "scripts/test_tool_domain_pdf_advanced.py")),
        Stage("Connaissance documentaire", (python, "scripts/test_tool_domain_document_knowledge.py")),
        Stage("Domaine d'outils Réseau", (python, "scripts/test_tool_domain_network.py")),
        Stage("Domaine d'outils Facturation", (python, "scripts/test_tool_domain_billing.py")),
        Stage("Domaine d'outils Windows", (python, "scripts/test_tool_domain_windows.py")),
        Stage("Domaine d'outils Web", (python, "scripts/test_tool_domain_web.py")),
        Stage(
            "Configuration SearXNG multi-moteurs",
            (python, "scripts/test_searxng_configuration.py"),
        ),
        Stage("Runtime HTTP et cache Web", (python, "scripts/test_web_runtime.py")),
        Stage("Transport HTTP sortant anti-SSRF", (python, "scripts/test_outbound_http.py")),
        Stage("Inspection Git bornée", (python, "scripts/test_tool_domain_git_repository.py")),
        Stage("Nettoyage système borné", (python, "scripts/test_tool_domain_system_cleanup.py")),
        Stage("Tâches longues compensables", (python, "scripts/test_tool_domain_long_tasks.py")),
        Stage("Auto-diagnostic borné", (python, "scripts/test_tool_domain_system_self_test.py")),
        Stage("Recherche unifiée traçable", (python, "scripts/test_tool_domain_unified_search.py")),
        Stage("Domaine de contrôle PC", (python, "scripts/test_tool_domain_pc_control.py")),
        Stage("Computer Runtime unifié", (python, "scripts/test_computer_runtime.py")),
        Stage("Lancement Windows et Tailscale", (python, "scripts/test_tailscale_runtime.py")),
        Stage("Domaine diagnostic PC", (python, "scripts/test_tool_domain_pc_diagnostics.py")),
        Stage("Documentation d'intervention", (python, "scripts/test_tool_domain_intervention_docs.py")),
        Stage("Sécurité des commandes", (python, "scripts/test_tool_domain_command_safety.py")),
        Stage("Contrôles opérationnels", (python, "scripts/test_tool_domain_operations_safety.py")),
        Stage("Santé client", (python, "scripts/test_tool_domain_client_health.py")),
        Stage("Domaine Winget", (python, "scripts/test_tool_domain_winget.py")),
        Stage("Paramètres Windows", (python, "scripts/test_tool_domain_windows_settings.py")),
        Stage("Registre Windows", (python, "scripts/test_tool_domain_windows_registry.py")),
        Stage("Tweaks Windows", (python, "scripts/test_tool_domain_windows_tweaks.py")),
        Stage("Nettoyage Catharsis", (python, "scripts/test_tool_domain_catharsis.py")),
        Stage("Recherche Windows", (python, "scripts/test_tool_domain_system_search.py")),
        Stage("Domaine ITSM", (python, "scripts/test_tool_domain_itsm.py")),
        Stage("Observabilité runtime", (python, "scripts/test_tool_domain_runtime_observability.py")),
        Stage("Domaine Google Drive", (python, "scripts/test_tool_domain_google_drive.py")),
        Stage("Domaine OneDrive", (python, "scripts/test_tool_domain_onedrive.py")),
        Stage("Domaine Google Calendar", (python, "scripts/test_tool_domain_google_calendar.py")),
        Stage("Abonnements calendrier", (python, "scripts/test_tool_domain_calendar_subscriptions.py")),
        Stage("Événements agenda", (python, "scripts/test_tool_domain_calendar_events.py")),
        Stage("Utilitaires déterministes", (python, "scripts/test_tool_domain_deterministic_utilities.py")),
        Stage("Date et heure déterministes", (python, "scripts/test_tool_domain_datetime.py")),
        Stage("Conversions d'unités déterministes", (python, "scripts/test_tool_domain_unit_conversion.py")),
        Stage("Domaine météo Open-Meteo", (python, "scripts/test_tool_domain_weather.py")),
        Stage("Domaine traduction Ollama", (python, "scripts/test_tool_domain_translation.py")),
        Stage("Traitement textuel déterministe", (python, "scripts/test_tool_domain_text_processing.py")),
        Stage("Données structurées CSV et SQLite", (python, "scripts/test_tool_domain_structured_data.py")),
        Stage("Gateway commun de tous les outils", (python, "scripts/test_tool_gateway.py")),
        Stage("Domaine d'outils Quiz", (python, "scripts/test_tool_domain_quiz.py")),
        Stage("Domaine d'outils Base IT", (python, "scripts/test_tool_domain_it_knowledge.py")),
        Stage("Domaine d'outils Tâches et Notes", (python, "scripts/test_tool_domain_productivity.py")),
        Stage("Cohérence SQLite-Qdrant des notes", (python, "scripts/test_note_lifecycle.py")),
        Stage("Domaine d'outils Mémoire", (python, "scripts/test_tool_domain_memory.py")),
        Stage(
            "Cycle de vie cohérent de la mémoire",
            (python, "scripts/test_memory_lifecycle.py"),
        ),
        Stage("Domaine d'outils Média", (python, "scripts/test_tool_domain_media.py")),
        Stage("Transport SSH partagé", (python, "scripts/test_ssh_transport.py")),
        Stage("Domaine d'outils SSH", (python, "scripts/test_tool_domain_ssh.py")),
        Stage("Frontière unique du routeur SSH", (python, "scripts/test_ssh_router_boundary.py")),
        Stage("Frontière des comptes e-mail", (python, "scripts/test_email_accounts_boundary.py")),
        Stage("Frontière de la boîte e-mail", (python, "scripts/test_email_mailbox_boundary.py")),
        Stage("Frontière des préférences e-mail", (python, "scripts/test_email_preferences_boundary.py")),
        Stage("Frontière IA et automatisation e-mail", (python, "scripts/test_email_automation_boundary.py")),
        Stage("Frontière vidéo distante Replicate", (python, "scripts/test_video_remote_boundary.py")),
        Stage("Frontière montage vidéo local", (python, "scripts/test_video_editing_boundary.py")),
        Stage("Frontière génération vidéo IA locale", (python, "scripts/test_video_local_boundary.py")),
        Stage("Garde-fous d'intention", (python, "scripts/test_intent_guards.py")),
        Stage("Council Cloud et provenance", (python, "scripts/test_council.py")),
        Stage("Moteur Council injectable", (python, "scripts/test_model_council.py")),
        Stage("Raisonnement parallèle borné", (python, "scripts/test_parallel_reasoning.py")),
        Stage("Mode Ultra strictement cloud", (python, "scripts/test_cloud_only_routing.py")),
        Stage("Contrats et routage Marvin Cortex", (python, "scripts/test_cortex.py")),
        Stage("Marvin Forge et métriques de fiabilité", (python, "scripts/test_forge.py")),
        Stage("Frontier Arena et Evidence Fabric", (python, "scripts/test_frontier_arena.py")),
        Stage("Adaptive Team Runtime", (python, "scripts/test_adaptive_team.py")),
        Stage("Code Forge et qualité des scripts", (python, "scripts/test_code_forge.py")),
        Stage("Exécution Python bornée", (python, "scripts/test_python_execution.py")),
        Stage("Bundles multi-fichiers reproductibles", (python, "scripts/test_deliverable_bundle.py")),
        Stage("Production Contract Gate", (python, "scripts/test_production_contract.py")),
        Stage("Matrice de langages certifiés", (python, "scripts/test_language_matrix.py")),
        Stage("Advanced Coding Mission", (python, "scripts/test_coding_mission.py")),
        Stage("Repository Intelligence et worktrees isolés", (python, "scripts/test_repository_intelligence.py")),
        Stage("Superviseur Auto persistant", (python, "scripts/test_coding_jobs.py")),
        Stage("Service Code Workspace UI et chat", (python, "scripts/test_coding_service.py")),
        Stage("Engineering Knowledge Radar", (python, "scripts/test_engineering_radar.py")),
        Stage("Test Forge et conteneurs jetables", (python, "scripts/test_test_forge.py")),
        Stage("Runner Windows Sandbox", (python, "scripts/test_windows_test_runner.py")),
        Stage("Runner Windows natif Hyper-V", (python, "scripts/test_hyperv_test_runner.py")),
        Stage("Runner Debian natif Hyper-V", (python, "scripts/test_linux_test_runner.py")),
        Stage("Chemins portables et Known Folders Windows", (python, "scripts/test_platform_paths.py")),
        Stage("Bibliotheque locale et exports Marvin", (python, "scripts/test_storage_layout.py")),
        Stage("VM Lab et integrite des ISO", (python, "scripts/test_vm_lab.py")),
        Stage("Jobs VM Lab persistants et lecture seule", (python, "scripts/test_vm_lab_jobs.py")),
        Stage("Cortex Search et vérificateurs spécialisés", (python, "scripts/test_cortex_search.py")),
        Stage("Model Market et Research Swarm", (python, "scripts/test_model_market.py")),
        Stage("Evolution Lab et Mission Canvas", (python, "scripts/test_evolution_canvas.py")),
        Stage("Mission OS et preuves d'actions", (python, "scripts/test_mission_os.py")),
        Stage("Memory Mesh et Truth Ledger", (python, "scripts/test_knowledge_mesh.py")),
        Stage("Orchestrateur email sans effet de bord", (python, "scripts/test_email_orchestrator.py")),
        Stage("Domaine messages email", (python, "scripts/test_tool_domain_email_messages.py")),
        Stage("Domaine productivité email", (python, "scripts/test_tool_domain_email_productivity.py")),
        Stage("Domaine surveillance email", (python, "scripts/test_tool_domain_email_monitoring.py")),
        Stage("Domaine automatisation email", (python, "scripts/test_tool_domain_email_automation.py")),
        Stage("Notifications Telegram bornées", (python, "scripts/test_tool_domain_telegram.py")),
        Stage("Mini-applications Web atomiques", (python, "scripts/test_tool_domain_webapp.py")),
        Stage("Catalogue frontend des outils", ("node", "--no-warnings", "scripts/test_tools_catalog.mjs")),
        Stage("Rendu frontend des résultats d'outils", ("node", "scripts/test_tools_result_panel.mjs")),
        Stage("Carte frontend des fichiers générés", ("node", "scripts/test_generated_file_card.mjs")),
        Stage("Proxy Next et sessions LAN", ("node", "scripts/test_next_api_proxy.mjs")),
        Stage("Rendus structurés des outils du chat", ("node", "scripts/test_chat_tool_results.mjs")),
        Stage("Onglets vidéo locale", ("node", "--no-warnings", "scripts/test_video_local_tabs.mjs")),
        Stage("Panneaux des paramètres", ("node", "--no-warnings", "scripts/test_settings_panels.mjs")),
        Stage("Vues Devis et facturation", ("node", "--no-warnings", "scripts/test_devis_panels.mjs")),
        Stage("Workspace email multi-boîtes", ("node", "--no-warnings", "scripts/test_email_workspace.mjs")),
        Stage("Logos locaux atomiques", (python, "scripts/test_tool_domain_logos.py")),
        Stage("Coherence des dependances Python", (python, "-m", "pip", "check")),
        Stage("Compilation du backend Python", action="compile_backend"),
        Stage("Baseline et qualite du frontend", (npm, "run", "check:frontend-baseline")),
        Stage("Resilience du smoke HTTP", (python, "scripts/test_smoke_api_resilience.py")),
    ]
    build_skip = None
    if quick:
        build_skip = "Mode quick : build de production explicitement exclu."
    elif live:
        build_skip = "Mode live : le frontend actif interdit un build Next.js concurrent."
    result.append(Stage("Build de production Next.js", (npm, "run", "build"), skip_reason=build_skip))
    live_skip = None if live else "Services Marvin non requis dans ce mode; utiliser --live."
    result.extend(
        [
            Stage("Contrats HTTP des services", (python, "scripts/smoke_test_api.py"), skip_reason=live_skip),
            Stage("Parcours des pages", (python, "scripts/smoke_test_pages.py"), skip_reason=live_skip),
            Stage("Rendu du chat", (python, "scripts/smoke_test_chat.py"), skip_reason=live_skip),
            Stage("Sérialisation vocale navigateur", (python, "scripts/smoke_test_voice.py"), skip_reason=live_skip),
        ]
    )
    if len(result) != EXPECTED_STAGE_COUNT:
        raise RuntimeError(
            f"Plan de validation incomplet : {len(result)} etapes au lieu de {EXPECTED_STAGE_COUNT}."
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validation consolidee de Marvin")
    parser.add_argument("--quick", action="store_true", help="ignore le build Next.js")
    parser.add_argument("--live", action="store_true", help="teste les services deja demarres")
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="arrete explicitement au premier echec; par defaut toutes les etapes sont executees",
    )
    parser.add_argument(
        "--report",
        default="artifacts/check-marvin-report.json",
        help="rapport JSON atomique sous artifacts/",
    )
    args = parser.parse_args()

    try:
        selected = stages(quick=args.quick, live=args.live)
    except RuntimeError as exc:
        print(f"ECHEC: {exc}", file=sys.stderr)
        return 1

    results = execute_stages(selected, fail_fast=args.fail_fast)

    print(f"\n{'=' * 68}\nSYNTHESE\n{'=' * 68}")
    for result in results:
        label = "SKIP" if result.skipped else ("OK" if result.success else "ECHEC")
        suffix = f" - {result.reason}" if result.reason else ""
        print(f"[{label}] {result.name} ({result.duration_seconds:.1f}s){suffix}")

    try:
        write_report(
            results,
            expected_count=EXPECTED_STAGE_COUNT,
            quick=args.quick,
            live=args.live,
            fail_fast=args.fail_fast,
            output_path=ROOT / args.report,
        )
    except (OSError, ValueError) as exc:
        print(f"ECHEC: rapport non ecrit: {exc}", file=sys.stderr)
        return 1

    if not results or len(results) != EXPECTED_STAGE_COUNT or not all(result.success for result in results):
        failures = sum(not result.success and not result.skipped for result in results)
        print(f"Validation Marvin en echec - {failures} etape(s) en echec sur {len(results)} executee(s).")
        return 1
    executed = sum(not result.skipped for result in results)
    skipped = sum(result.skipped for result in results)
    print(f"Validation Marvin OK - {executed} executees, {skipped} ignorees sur {EXPECTED_STAGE_COUNT} attendues.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
