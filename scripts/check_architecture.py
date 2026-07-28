"""Contrôles statiques des invariants structurels de Marvin.

Le script n'importe pas le backend : il ne démarre ni Qdrant, ni SQLite, ni Ollama
et peut donc être exécuté sur une nouvelle machine avant le premier lancement.

Usage : python scripts/check_architecture.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


class CheckFailure(RuntimeError):
    pass


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def assignment(tree: ast.Module, name: str) -> ast.AST:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node.value
    raise CheckFailure(f"Affectation introuvable : {name}")


def literal_assignment(path: Path, name: str):
    return ast.literal_eval(assignment(parse(path), name))


def duplicates(values: list[str]) -> list[str]:
    return sorted(k for k, count in Counter(values).items() if count > 1)


def tool_names() -> tuple[list[str], list[str]]:
    tree = parse(BACKEND / "tools.py")

    registry_node = assignment(tree, "TOOLS_REGISTRY")
    if not isinstance(registry_node, ast.Dict):
        raise CheckFailure("TOOLS_REGISTRY doit rester un dictionnaire littéral.")
    registry = [ast.literal_eval(key) for key in registry_node.keys]

    spec_node = assignment(tree, "TOOLS_SPEC")
    if not isinstance(spec_node, ast.List):
        raise CheckFailure("TOOLS_SPEC doit rester une liste littérale.")
    spec: list[str] = []
    for item in spec_node.elts:
        if not (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id == "_t"
            and item.args
            and isinstance(item.args[0], ast.Constant)
            and isinstance(item.args[0].value, str)
        ):
            raise CheckFailure("Chaque entrée TOOLS_SPEC doit utiliser _t(\"nom\", ...).")
        spec.append(item.args[0].value)
    return registry, spec


def fastapi_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    methods = {"get", "post", "put", "delete", "patch", "websocket"}
    sources = [BACKEND / "main.py", *(BACKEND / "api").rglob("*.py")]
    for source in sources:
        tree = parse(source)
        router_prefix = ""
        for statement in tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "router" for target in statement.targets):
                continue
            value = statement.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "APIRouter"):
                continue
            for keyword in value.keywords:
                if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    router_prefix = keyword.value.value.rstrip("/")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and isinstance(deco.func.value, ast.Name)
                    and deco.func.value.id in {"app", "router"}
                    and deco.func.attr in methods
                    and deco.args
                    and isinstance(deco.args[0], ast.Constant)
                ):
                    continue
                path = deco.args[0].value
                if deco.func.value.id == "router":
                    path = router_prefix + (path if path.startswith("/") else "/" + path)
                routes.append((deco.func.attr.upper(), path or "/"))
    return routes


def smoke_pages() -> tuple[set[str], set[str]]:
    expected = {"/"}
    for child in (ROOT / "app").iterdir():
        if child.is_dir() and child.name != "api" and any(
            (child / name).exists() for name in ("page.js", "page.jsx")
        ):
            expected.add(f"/{child.name}")

    configured = set(literal_assignment(ROOT / "scripts" / "smoke_test_pages.py", "PAGES"))
    return expected, configured


def check_backend_url_is_centralized() -> list[Path]:
    offenders: list[Path] = []
    legacy = re.compile(r"window\.location\.hostname\s*\+\s*['\"]:8005")
    for base in (ROOT / "app", ROOT / "components", ROOT / "lib"):
        for path in [*base.rglob("*.js"), *base.rglob("*.jsx")]:
            if path == ROOT / "lib" / "backend.js":
                continue
            if legacy.search(path.read_text(encoding="utf-8-sig")):
                offenders.append(path.relative_to(ROOT))
    return sorted(offenders)


def run() -> dict[str, int | str]:
    version = literal_assignment(BACKEND / "app_version.py", "APP_VERSION")
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    package_version = package["version"]
    lock_version = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))["version"]
    if len({version, package_version, lock_version}) != 1:
        raise CheckFailure(
            f"Versions désynchronisées : backend={version}, package={package_version}, lock={lock_version}"
        )
    readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8-sig")
    if f"Version {version}" not in readme or f"(v{version})" not in agents:
        raise CheckFailure("README.md ou AGENTS.md n'annonce pas la version publique courante.")
    logging_policy_path = ROOT / "MARVIN-LOGGING-POLICY.md"
    if not logging_policy_path.is_file():
        raise CheckFailure("La politique obligatoire de journalisation est absente.")
    logging_policy = logging_policy_path.read_text(encoding="utf-8-sig")
    for marker in (
        "OpenTelemetry Logs Data Model",
        "OWASP Logging Cheat Sheet",
        "NIST SP 800-92",
        "Données interdites",
        "Rotation, rétention et budget disque",
        "test de non-divulgation",
    ):
        if marker not in logging_policy:
            raise CheckFailure(f"Politique de journalisation incomplète : {marker}")
    structured_source = (BACKEND / "structured_logging.py").read_text(encoding="utf-8-sig")
    for marker in (
        "StructuredJsonlStore",
        "retention_days",
        "max_total_bytes",
        "trace_id",
        "sanitize",
    ):
        if marker not in structured_source:
            raise CheckFailure(f"Fondation de journalisation incomplète : {marker}")
    persistence_inventory_path = ROOT / "MARVIN-PERSISTENCE-INVENTORY.md"
    if not persistence_inventory_path.is_file():
        raise CheckFailure("L'inventaire autoritaire des persistances JSONL est absent.")
    persistence_inventory = persistence_inventory_path.read_text(encoding="utf-8-sig")
    for marker in (
        "technical_log",
        "domain_event_stream",
        "evaluation_ledger",
        "truth_ledger",
        "persistence-inventory",
    ):
        if marker not in persistence_inventory:
            raise CheckFailure(f"Inventaire de persistance incomplet : {marker}")
    evidence_source = (BACKEND / "durable_evidence_store.py").read_text(encoding="utf-8-sig")
    for marker in (
        "DurableEvidenceStore",
        "record_hash",
        "previous_hash",
        "_interprocess_lock",
        "owner_lifecycle",
    ):
        if marker not in evidence_source:
            raise CheckFailure(f"Registre de preuves incomplet : {marker}")

    required_scripts = {
        "check:runtime",
        "check:generation-runtime",
        "check:structured-logging",
        "check:skill-match-logging",
        "check:persistence-inventory",
        "check:durable-evidence",
        "check:forge-evidence",
        "check:credentials-vault",
        "check:agent-gateway-api",
        "check:model-proactive-api",
        "check:main-composition",
        "check:architecture",
        "check:frontier-contract",
        "check:telegram",
        "check:webapp",
        "check:logos",
        "check:runtime-supervisor",
        "check:runtime-workers",
        "check:communication-workers",
        "check:proactive-service",
        "check:cron-runtime",
        "check:agent-routing",
        "check:agent-prompt",
        "check:agent-tool-selection",
        "check:action-replay",
        "check:chat-turn-runtime",
        "check:chat-stream",
        "check:tool-domain-quiz",
        "check:tool-domain-it-knowledge",
        "check:intents",
        "check:council",
        "check:cortex",
        "check:forge",
        "check:arena",
        "check:adaptive-team",
        "check:code-forge",
        "check:test-forge",
        "check:hyperv-test-forge",
        "check:platform-paths",
        "check:storage-layout",
        "check:vm-lab",
        "check:cortex-search",
        "check:model-market",
        "check:evolution",
        "check:missions",
        "check:knowledge",
        "check:engineering-radar",
        "check:api",
        "check:pages",
        "check:chat",
        "check:quick",
        "check",
        "check:live",
    }
    missing_scripts = sorted(required_scripts - set(package.get("scripts", {})))
    if missing_scripts:
        raise CheckFailure(f"Commandes npm de validation manquantes : {missing_scripts}")

    required_files = [
        ROOT / "ACTIVER-HYPERV-MARVIN.bat",
        ROOT / "stop.bat",
        ROOT / "scripts" / "stop-marvin.ps1",
        ROOT / "SECURITY-DEBT-REGISTER.md",
        ROOT / "scripts" / "check_runtime.mjs",
        ROOT / "scripts" / "check_marvin.py",
        ROOT / "scripts" / "test_runtime_supervisor.py",
        ROOT / "scripts" / "test_runtime_workers.py",
        ROOT / "scripts" / "test_communication_workers.py",
        ROOT / "scripts" / "test_proactive_service.py",
        ROOT / "scripts" / "test_cron_runtime.py",
        ROOT / "scripts" / "test_db_migrations.py",
        ROOT / "scripts" / "test_database_init.mjs",
        ROOT / "scripts" / "test_conversation_repository.py",
        ROOT / "scripts" / "test_settings_repository.py",
        ROOT / "scripts" / "test_personal_data_repositories.py",
        ROOT / "scripts" / "test_event_repository.py",
        ROOT / "scripts" / "test_project_artifact_repositories.py",
        ROOT / "scripts" / "test_execution_repository.py",
        ROOT / "scripts" / "test_operational_state_repositories.py",
        ROOT / "scripts" / "test_billing_repository.py",
        ROOT / "scripts" / "test_db_connection_hygiene.py",
        ROOT / "scripts" / "test_credentials_vault.py",
        ROOT / "scripts" / "test_agent_gateway_api.py",
        ROOT / "scripts" / "test_model_proactive_api.py",
        ROOT / "scripts" / "test_main_composition.py",
        ROOT / "scripts" / "rollback-credentials-vault.py",
        ROOT / "scripts" / "test_agent_policy.py",
        ROOT / "scripts" / "test_agent_safety.py",
        ROOT / "scripts" / "test_tool_domain_datetime.py",
        ROOT / "scripts" / "test_tool_domain_unit_conversion.py",
        ROOT / "scripts" / "test_tool_domain_weather.py",
        ROOT / "scripts" / "test_tool_domain_translation.py",
        ROOT / "scripts" / "test_agent_protocol.py",
        ROOT / "scripts" / "test_generation_runtime.py",
        ROOT / "scripts" / "test_agent_routing.py",
        ROOT / "scripts" / "test_agent_prompt.py",
        ROOT / "scripts" / "test_agent_tool_selection.py",
        ROOT / "scripts" / "test_action_replay.py",
        ROOT / "scripts" / "test_chat_turn_runtime.py",
        ROOT / "scripts" / "test_chat_stream.mjs",
        ROOT / "scripts" / "test_tool_domain_quiz.py",
        ROOT / "scripts" / "test_tool_domain_it_knowledge.py",
        ROOT / "scripts" / "test_intent_guards.py",
        ROOT / "scripts" / "test_council.py",
        ROOT / "scripts" / "test_cortex.py",
        ROOT / "scripts" / "test_forge.py",
        ROOT / "scripts" / "test_frontier_arena.py",
        ROOT / "scripts" / "test_adaptive_team.py",
        ROOT / "scripts" / "test_code_forge.py",
        ROOT / "scripts" / "test_deliverable_bundle.py",
        ROOT / "scripts" / "test_production_contract.py",
        ROOT / "scripts" / "test_language_matrix.py",
        ROOT / "scripts" / "test_coding_mission.py",
        ROOT / "scripts" / "test_repository_intelligence.py",
        ROOT / "scripts" / "test_coding_jobs.py",
        ROOT / "scripts" / "test_test_forge.py",
        ROOT / "scripts" / "test_hyperv_test_runner.py",
        ROOT / "scripts" / "test_platform_paths.py",
        ROOT / "scripts" / "test_storage_layout.py",
        ROOT / "scripts" / "test_vm_lab.py",
        ROOT / "scripts" / "provision-vm-lab.ps1",
        ROOT / "PROVISIONNER-VM-LAB-MARVIN.bat",
        ROOT / "scripts" / "remove-legacy-hyperv-vms.ps1",
        ROOT / "scripts" / "audit-hyperv-store-admin.ps1",
        ROOT / "AUDITER-MAGASIN-HYPERV.bat",
        ROOT / "scripts" / "cleanup-hyperv-orphan-cache-admin.ps1",
        ROOT / "scripts" / "invoke-cleanup-hyperv.ps1",
        ROOT / "NETTOYER-CACHE-HYPERV.bat",
        ROOT / "SUPPRIMER-ANCIENNES-VM.bat",
        ROOT / "scripts" / "prepare-hyperv-test-forge.ps1",
        ROOT / "HYPERV-TEST-FORGE.md",
        ROOT / "scripts" / "test_cortex_search.py",
        ROOT / "scripts" / "test_model_market.py",
        ROOT / "scripts" / "test_evolution_canvas.py",
        ROOT / "scripts" / "test_mission_os.py",
        ROOT / "scripts" / "test_knowledge_mesh.py",
        ROOT / "scripts" / "test_engineering_radar.py",
        ROOT / "scripts" / "test_frontier_consolidation_contract.py",
        ROOT / "scripts" / "test_tool_domain_telegram.py",
        ROOT / "scripts" / "test_tool_domain_webapp.py",
        ROOT / "scripts" / "test_tool_domain_logos.py",
        ROOT / "scripts" / "smoke_test_api.py",
    ]
    missing_files = [str(path.relative_to(ROOT)) for path in required_files if not path.exists()]
    if missing_files:
        raise CheckFailure(f"Fichiers du socle de validation manquants : {missing_files}")

    verifier = (ROOT / "VERIFIER-INSTALLATION.bat").read_text(encoding="utf-8-sig")
    if "import tools, main" in verifier:
        raise CheckFailure("Le docteur d'installation ne doit jamais importer main/Qdrant hors API.")
    starter = (ROOT / "start.bat").read_text(encoding="utf-8-sig")
    if "check_runtime.mjs" not in starter or "/api/health" not in starter:
        raise CheckFailure("start.bat doit conserver le preflight runtime et le controle HTTP.")
    consolidation_plan = (ROOT / "BACKEND-CONSOLIDATION-PLAN.md").read_text(
        encoding="utf-8-sig"
    )
    if (
        "gate de rollback obligatoire" not in consolidation_plan.lower()
        or "réversibilité vérifiée" not in consolidation_plan.lower()
    ):
        raise CheckFailure(
            "Le plan de consolidation doit conserver le gate de rollback vérifiable."
        )

    frontier_contract = (ROOT / "MARVIN-FRONTIER-CONSOLIDATION.md").read_text(
        encoding="utf-8-sig"
    )
    if (
        "## 4. Matrice exhaustive" not in frontier_contract
        or "<!-- frontier-matrix" not in frontier_contract
        or "git apply --cached --check --reverse" not in frontier_contract
    ):
        raise CheckFailure(
            "Le contrat de consolidation globale doit conserver matrice et rollback."
        )

    main_source = (BACKEND / "main.py").read_text(encoding="utf-8-sig")
    health_source = (BACKEND / "api" / "health.py").read_text(encoding="utf-8-sig")
    if 'version=APP_VERSION' not in main_source or '"version": APP_VERSION' not in health_source:
        raise CheckFailure("FastAPI et /api/health doivent utiliser APP_VERSION.")
    for route_file in (BACKEND / "api").glob("*.py"):
        if route_file.name == "__init__.py":
            continue
        module = route_file.stem
        alias = f"{module}_router"
        if (
            f"from api.{module} import router as {alias}" not in main_source
            or f"app.include_router({alias})" not in main_source
        ):
            raise CheckFailure(f"Le routeur api/{route_file.name} n'est pas monte dans main.py.")

    registry, spec = tool_names()
    if duplicates(registry):
        raise CheckFailure(f"Outils dupliqués dans TOOLS_REGISTRY : {duplicates(registry)}")
    if duplicates(spec):
        raise CheckFailure(f"Outils dupliqués dans TOOLS_SPEC : {duplicates(spec)}")
    if set(registry) != set(spec):
        missing_spec = sorted(set(registry) - set(spec))
        missing_registry = sorted(set(spec) - set(registry))
        raise CheckFailure(
            f"Registre et schémas désynchronisés : sans spec={missing_spec}, sans exécuteur={missing_registry}"
        )

    dangerous = literal_assignment(BACKEND / "config.py", "DANGEROUS_TOOLS")
    secure_blocked = literal_assignment(BACKEND / "config.py", "SECURE_BLOCKED_TOOLS")
    unknown_guarded = sorted((dangerous | secure_blocked) - set(registry))
    if unknown_guarded:
        raise CheckFailure(f"Permissions visant des outils inexistants : {unknown_guarded}")
    gateway_source = (BACKEND / "api" / "agent_gateway.py").read_text(
        encoding="utf-8-sig"
    )
    if (
        "tool_gateway.execute_tool(" not in gateway_source
        or "tool_gateway.coverage_report(" not in gateway_source
    ):
        raise CheckFailure(
            "Les surfaces UI/MCP et le catalogue doivent utiliser le gateway commun."
        )

    routes = fastapi_routes()
    if duplicates([f"{method} {path}" for method, path in routes]):
        raise CheckFailure("Une route FastAPI méthode+chemin est déclarée plusieurs fois.")

    expected_pages, configured_pages = smoke_pages()
    if expected_pages != configured_pages:
        raise CheckFailure(
            "Couverture Playwright incomplète : "
            f"manquantes={sorted(expected_pages - configured_pages)}, "
            f"obsolètes={sorted(configured_pages - expected_pages)}"
        )

    url_offenders = check_backend_url_is_centralized()
    if url_offenders:
        raise CheckFailure(f"URL backend redéfinie hors lib/backend.js : {url_offenders}")

    return {
        "version": version,
        "tools": len(registry),
        "routes": len(routes),
        "pages": len(expected_pages),
        "harness_tools": len(set(registry) & set(spec)),
        "restricted_tools": len(dangerous | secure_blocked),
    }


def main() -> int:
    try:
        result = run()
    except (CheckFailure, SyntaxError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ECHEC architecture : {exc}")
        return 1
    print(
        "Architecture OK - "
        f"Marvin {result['version']} | {result['tools']} outils | "
        f"{result['routes']} routes | {result['pages']} pages | "
        f"harness {result['harness_tools']}/{result['tools']} | "
        f"{result['restricted_tools']} restrictions renforcees"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
