"""Orchestrateur des controles reproductibles de Marvin.

Ce script ne démarre jamais FastAPI ni Qdrant dans un second processus. Les contrôles
live passent exclusivement par HTTP afin de ne pas ouvrir Qdrant hors de FastAPI.
"""

from __future__ import annotations

import argparse
import os
import py_compile
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VENV_PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"


@dataclass(frozen=True)
class Stage:
    name: str
    command: tuple[str, ...] | None = None
    action: str | None = None


def npm_command() -> str:
    command = shutil.which("npm.cmd") or shutil.which("npm")
    if not command:
        raise RuntimeError("npm est introuvable dans PATH.")
    return command


def compile_backend() -> None:
    files = [
        path
        for path in BACKEND.rglob("*.py")
        if not {".venv", "data", "generated_videos"}.intersection(path.parts)
    ]
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
        )
        return completed.returncode == 0, time.perf_counter() - started
    except (OSError, RuntimeError, py_compile.PyCompileError) as exc:
        print(f"ECHEC: {exc}", file=sys.stderr)
        return False, time.perf_counter() - started


def stages(*, quick: bool, live: bool) -> list[Stage]:
    if not VENV_PYTHON.exists():
        raise RuntimeError("backend/.venv est absent. Lancez INSTALLER-NOUVEAU-PC.bat.")

    python = str(VENV_PYTHON)
    npm = npm_command()
    result = [
        Stage("Runtime Node et modules natifs", ("node", "scripts/check_runtime.mjs")),
        Stage("Installation Windows portable", (python, "scripts/test_installer_contract.py")),
        Stage("Activation locale de l'avatar", (python, "scripts/test_avatar_api.py")),
        Stage("Invariants d'architecture", (python, "scripts/check_architecture.py")),
        Stage("Superviseur idempotent des workers", (python, "scripts/test_runtime_supervisor.py")),
        Stage("Workers de maintenance extraits", (python, "scripts/test_runtime_workers.py")),
        Stage("Workers e-mail et agenda extraits", (python, "scripts/test_communication_workers.py")),
        Stage("Service proactif et voix du briefing", (python, "scripts/test_proactive_service.py")),
        Stage("Moteur cron et reprises longues", (python, "scripts/test_cron_runtime.py")),
        Stage("Migrations SQLite transactionnelles", (python, "scripts/test_db_migrations.py")),
        Stage("Initialisation SQLite Next.js", ("node", "--no-warnings", "scripts/test_database_init.mjs")),
        Stage("Repository conversations et messages", (python, "scripts/test_conversation_repository.py")),
        Stage("Repository des connexions SSH", (python, "scripts/test_ssh_connection_repository.py")),
        Stage("Repository des workflows", (python, "scripts/test_workflow_repository.py")),
        Stage("Fermeture garantie des connexions SQLite", (python, "scripts/test_db_connection_hygiene.py")),
        Stage("Politiques textuelles de l'agent", (python, "scripts/test_agent_policy.py")),
        Stage("Sécurité déterministe de l'agent", (python, "scripts/test_agent_safety.py")),
        Stage("Protocole messages Ollama et SSE", (python, "scripts/test_agent_protocol.py")),
        Stage("Transport HTTP et JSONL Ollama", (python, "scripts/test_agent_transport.py")),
        Stage("Routage des profils et modeles", (python, "scripts/test_agent_routing.py")),
        Stage("Construction du prompt systeme", (python, "scripts/test_agent_prompt.py")),
        Stage("Selection bornee des outils LLM", (python, "scripts/test_agent_tool_selection.py")),
        Stage("Execution deterministe des outils LLM", (python, "scripts/test_agent_execution.py")),
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
        Stage("Revue indépendante des réponses et actions", (python, "scripts/test_agent_review.py")),
        Stage("Contexte de session et captures", (python, "scripts/test_agent_context.py")),
        Stage("Préparation durable d'un tour", (python, "scripts/test_agent_session.py")),
        Stage("Compilation du plan de tour", (python, "scripts/test_agent_planning.py")),
        Stage("Matérialisation des outils obligatoires", (python, "scripts/test_agent_required_tools.py")),
        Stage("Configuration modèle et confidentialité", (python, "scripts/test_agent_model_config.py")),
        Stage("État observable du Runner", (python, "scripts/test_agent_runner.py")),
        Stage("Observabilité du Runner", (python, "scripts/test_agent_observability.py")),
        Stage("Finalisation commune du Runner", (python, "scripts/test_agent_finalization.py")),
        Stage("Recus idempotents des actions chat", (python, "scripts/test_action_replay.py")),
        Stage("Tours chat durables et detachables", (python, "scripts/test_chat_turn_runtime.py")),
        Stage("Reconnexion SSE du frontend", ("node", "--no-warnings", "scripts/test_chat_stream.mjs")),
        Stage("Domaine d'outils Quiz", (python, "scripts/test_tool_domain_quiz.py")),
        Stage("Domaine d'outils Base IT", (python, "scripts/test_tool_domain_it_knowledge.py")),
        Stage("Domaine d'outils Tâches et Notes", (python, "scripts/test_tool_domain_productivity.py")),
        Stage("Domaine d'outils Mémoire", (python, "scripts/test_tool_domain_memory.py")),
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
        Stage("Mode Ultra strictement cloud", (python, "scripts/test_cloud_only_routing.py")),
        Stage("Contrats et routage Marvin Cortex", (python, "scripts/test_cortex.py")),
        Stage("Marvin Forge et métriques de fiabilité", (python, "scripts/test_forge.py")),
        Stage("Frontier Arena et Evidence Fabric", (python, "scripts/test_frontier_arena.py")),
        Stage("Adaptive Team Runtime", (python, "scripts/test_adaptive_team.py")),
        Stage("Code Forge et qualité des scripts", (python, "scripts/test_code_forge.py")),
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
        Stage("Cortex Search et vérificateurs spécialisés", (python, "scripts/test_cortex_search.py")),
        Stage("Model Market et Research Swarm", (python, "scripts/test_model_market.py")),
        Stage("Evolution Lab et Mission Canvas", (python, "scripts/test_evolution_canvas.py")),
        Stage("Mission OS et preuves d'actions", (python, "scripts/test_mission_os.py")),
        Stage("Memory Mesh et Truth Ledger", (python, "scripts/test_knowledge_mesh.py")),
        Stage("Orchestrateur email sans effet de bord", (python, "scripts/test_email_orchestrator.py")),
        Stage("Coherence des dependances Python", (python, "-m", "pip", "check")),
        Stage("Compilation du backend Python", action="compile_backend"),
        Stage("Qualite du frontend", (npm, "run", "lint")),
    ]
    if not quick and not live:
        result.append(Stage("Build de production Next.js", (npm, "run", "build")))
    if live:
        result.extend(
            [
                Stage("Contrats HTTP des services", (python, "scripts/smoke_test_api.py")),
                Stage("Parcours des pages", (python, "scripts/smoke_test_pages.py")),
                Stage("Rendu du chat", (python, "scripts/smoke_test_chat.py")),
                Stage("Sérialisation vocale navigateur", (python, "scripts/smoke_test_voice.py")),
            ]
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validation consolidee de Marvin")
    parser.add_argument("--quick", action="store_true", help="ignore le build Next.js")
    parser.add_argument("--live", action="store_true", help="teste les services deja demarres")
    args = parser.parse_args()

    try:
        selected = stages(quick=args.quick, live=args.live)
    except RuntimeError as exc:
        print(f"ECHEC: {exc}", file=sys.stderr)
        return 1

    results: list[tuple[str, bool, float]] = []
    for stage in selected:
        success, duration = run_stage(stage)
        results.append((stage.name, success, duration))
        if not success:
            break

    print(f"\n{'=' * 68}\nSYNTHESE\n{'=' * 68}")
    for name, success, duration in results:
        print(f"[{'OK' if success else 'ECHEC'}] {name} ({duration:.1f}s)")

    if not results or not all(success for _, success, _ in results):
        print("Validation Marvin en echec.")
        return 1
    print(f"Validation Marvin OK - {len(results)} etapes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
