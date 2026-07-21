"""Smoke test HTTP en lecture seule des contrats essentiels de Marvin."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any


BACKEND = os.getenv("MARVIN_BACKEND_URL", "http://127.0.0.1:8005").rstrip("/")
FRONTEND = os.getenv("MARVIN_FRONTEND_URL", "http://127.0.0.1:3000").rstrip("/")
OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise AssertionError(f"HTTP {response.status} pour {url}")
        return json.loads(response.read().decode("utf-8"))


def fetch_ok(url: str) -> None:
    with urllib.request.urlopen(url, timeout=20) as response:
        if response.status != 200:
            raise AssertionError(f"HTTP {response.status} pour {url}")


def post_json(url: str, payload: dict) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def backend_health() -> None:
    data = fetch_json(f"{BACKEND}/api/health")
    assert data.get("status") == "ok"
    assert data.get("backend") == "python-fastapi"
    assert data.get("tools_count", 0) > 0
    assert data.get("tools_count") == data.get("tools_spec_count")
    assert isinstance(data.get("ollama"), bool)
    assert isinstance(data.get("version"), str) and data["version"].count(".") == 2


def backend_openapi() -> None:
    data = fetch_json(f"{BACKEND}/openapi.json")
    paths = data.get("paths", {})
    methods = {"get", "post", "put", "delete", "patch", "options", "head"}
    operations = sum(
        1 for definitions in paths.values() for method in definitions if method in methods
    )
    assert len(paths) >= 200, f"Seulement {len(paths)} chemins OpenAPI"
    assert operations >= 250, f"Seulement {operations} operations OpenAPI"
    assert "get" in paths.get("/api/health", {})


def ollama_tags() -> None:
    data = fetch_json(f"{OLLAMA}/api/tags")
    assert isinstance(data.get("models"), list)


def frontend_status() -> None:
    data = fetch_json(f"{FRONTEND}/api/status")
    assert isinstance(data.get("ollama"), dict)
    assert isinstance(data["ollama"].get("connected"), bool)


def frontend_settings() -> None:
    data = fetch_json(f"{FRONTEND}/api/settings")
    assert data.get("success") is True
    assert isinstance(data.get("models"), list)


def conversations_contract() -> None:
    conversations = fetch_json(f"{BACKEND}/api/conversations?limit=2&offset=0")
    assert isinstance(conversations, list)
    search = fetch_json(
        f"{BACKEND}/api/conversations/search?q=__marvin_smoke_missing__&limit=2"
    )
    assert isinstance(search, list)
    if conversations:
        conversation_id = conversations[0].get("id")
        assert isinstance(conversation_id, str) and conversation_id
        detail = fetch_json(f"{BACKEND}/api/conversations/{conversation_id}")
        assert detail.get("conversation", {}).get("id") == conversation_id
        assert isinstance(detail.get("messages"), list)
        for message in detail["messages"][:5]:
            assert isinstance(message.get("parts"), list)
            assert isinstance(message.get("toolInvocations"), list)


def organizer_contracts() -> None:
    projects = fetch_json(f"{BACKEND}/api/projects")
    tasks = fetch_json(f"{BACKEND}/api/tasks")
    filtered_tasks = fetch_json(f"{BACKEND}/api/tasks?status=pending")
    notes = fetch_json(f"{BACKEND}/api/notes")
    searched_notes = fetch_json(f"{BACKEND}/api/notes?search=__marvin_smoke_missing__")
    for payload in (projects, tasks, filtered_tasks, notes, searched_notes):
        assert isinstance(payload, list)


def local_data_contracts() -> None:
    memories = fetch_json(f"{BACKEND}/api/memories")
    setting = fetch_json(f"{BACKEND}/api/settings/permission_level")
    backups = fetch_json(f"{BACKEND}/api/backups")
    preview = fetch_json(f"{BACKEND}/api/memories/consolidate/preview")
    assert isinstance(memories, list)
    assert setting.get("key") == "permission_level"
    assert "value" in setting
    assert isinstance(backups, list)
    assert preview.get("dry_run") is True
    assert isinstance(preview.get("merges"), list)


def history_and_templates_contracts() -> None:
    history = fetch_json(f"{BACKEND}/api/history?limit=1&offset=0")
    stats = fetch_json(f"{BACKEND}/api/history/stats")
    reliability = fetch_json(
        f"{BACKEND}/api/history/reliability?min_calls=999999&days=1&recent_days=1"
    )
    templates = fetch_json(f"{BACKEND}/api/templates")
    assert isinstance(history, list)
    assert isinstance(stats.get("total"), int)
    assert isinstance(stats.get("by_tool"), list)
    assert isinstance(reliability.get("tools"), list)
    assert isinstance(templates, list)


def business_contracts() -> None:
    clients = fetch_json(f"{BACKEND}/api/billing/clients")
    quotes = fetch_json(f"{BACKEND}/api/billing/quotes")
    catalog = fetch_json(f"{BACKEND}/api/billing/catalog")
    interventions = fetch_json(f"{BACKEND}/api/docs/interventions?limit=1")
    documents = fetch_json(f"{BACKEND}/api/docs/documents")
    doc_templates = fetch_json(f"{BACKEND}/api/docs/templates")
    assets = fetch_json(f"{BACKEND}/api/docs/assets")
    checks = fetch_json(f"{BACKEND}/api/ops/checks")
    evidence = fetch_json(f"{BACKEND}/api/ops/evidence")
    reviews = fetch_json(f"{BACKEND}/api/cmd/reviews?limit=1")
    rules = fetch_json(f"{BACKEND}/api/cmd/rules")
    approvals = fetch_json(f"{BACKEND}/api/cmd/approvals")
    missing_id = "__marvin_smoke_missing__"
    score = fetch_json(f"{BACKEND}/api/client-health/{missing_id}")
    score_history = fetch_json(f"{BACKEND}/api/client-health/{missing_id}/history?limit=1")
    recommendations = fetch_json(
        f"{BACKEND}/api/client-health/{missing_id}/recommendations"
    )
    expected_lists = (
        (clients, "clients"),
        (quotes, "quotes"),
        (catalog, "services"),
        (interventions, "interventions"),
        (documents, "documents"),
        (doc_templates, "templates"),
        (assets, "assets"),
        (checks, "checks"),
        (evidence, "evidence"),
        (reviews, "reviews"),
        (rules, "rules"),
        (approvals, "approvals"),
        (score_history, "history"),
        (recommendations, "recommendations"),
    )
    for payload, key in expected_lists:
        assert isinstance(payload.get(key), list)
    assert "score" in score


def diagnostics_and_documents_contracts() -> None:
    network = fetch_json(f"{BACKEND}/api/network")
    documents = fetch_json(f"{BACKEND}/api/documents")
    templates = fetch_json(f"{BACKEND}/api/documents/templates")
    letterhead = fetch_json(f"{BACKEND}/api/documents/letterhead")
    assert isinstance(network.get("hostname"), str)
    assert isinstance(network.get("addresses"), list)
    assert isinstance(documents, (list, dict))
    assert isinstance(templates.get("templates"), list)
    assert isinstance(letterhead, dict)


def calendar_contracts() -> None:
    events = fetch_json(f"{BACKEND}/api/events?period=today")
    subscriptions = fetch_json(f"{BACKEND}/api/calendar/subscriptions")
    assert isinstance(events, dict)
    assert isinstance(subscriptions, dict)


def multi_agents_contract() -> None:
    result = post_json(f"{BACKEND}/api/agents/parallel", {"tasks": []})
    assert result.get("count") == 0
    assert result.get("results") == []
    assert isinstance(result.get("total_ms"), int)


def workflows_contract() -> None:
    workflows = fetch_json(f"{BACKEND}/api/workflows")
    assert isinstance(workflows, list)
    if workflows:
        workflow_id = workflows[0].get("id")
        assert isinstance(workflow_id, str) and workflow_id
        detail = fetch_json(f"{BACKEND}/api/workflows/{workflow_id}")
        runs = fetch_json(f"{BACKEND}/api/workflows/{workflow_id}/runs?limit=1")
        assert detail.get("id") == workflow_id
        assert isinstance(runs, list)


def voice_contract() -> None:
    voices = fetch_json(f"{BACKEND}/api/voice/voices")
    assert voices.get("default") == "henri"
    assert isinstance(voices.get("voices"), list) and voices["voices"]


def runtime_config_contracts() -> None:
    telegram = fetch_json(f"{BACKEND}/api/telegram")
    learning = fetch_json(f"{BACKEND}/api/learning")
    auto_config = fetch_json(f"{BACKEND}/api/auto-config")
    modes = fetch_json(f"{BACKEND}/api/perf-modes")
    audit = fetch_json(f"{BACKEND}/api/audit?limit=1")
    assert "bot_token" not in telegram
    assert isinstance(telegram.get("has_token"), bool)
    assert isinstance(learning.get("counts"), dict)
    assert isinstance(auto_config, dict)
    assert isinstance(modes.get("modes"), list)
    assert isinstance(audit.get("actions"), list)
    assert isinstance(audit.get("stats"), dict)


def skills_contracts() -> None:
    payload = fetch_json(f"{BACKEND}/api/skills")
    stats = fetch_json(f"{BACKEND}/api/skills/stats")
    learning_log = fetch_json(f"{BACKEND}/api/skills/learning_log?limit=1")
    match_log = fetch_json(f"{BACKEND}/api/skills/match_log?limit=1")
    assert isinstance(payload.get("skills"), list)
    assert isinstance(stats.get("stats"), dict)
    assert isinstance(learning_log.get("log"), list)
    assert isinstance(match_log.get("log"), list)


def content_contracts() -> None:
    paths = fetch_json(f"{BACKEND}/api/system/paths")
    assert isinstance(paths.get("home"), str) and paths["home"]
    assert isinstance(paths.get("username"), str)


def storage_contracts() -> None:
    layout = fetch_json(f"{BACKEND}/api/storage/layout")
    proxy_layout = fetch_json(f"{FRONTEND}/api/storage/layout")
    assert isinstance(layout.get("machine_root"), str) and layout["machine_root"]
    assert isinstance(layout.get("export_root"), str) and layout["export_root"]
    assert isinstance(layout.get("directories"), dict)
    assert isinstance(layout.get("iso_inventory"), list)
    assert layout.get("machine", {}).get("drive_type") in {"fixed", "local"}
    assert proxy_layout.get("machine_root") == layout.get("machine_root")


def vm_lab_contracts() -> None:
    lab = fetch_json(f"{BACKEND}/api/vm-lab/status")
    proxy_lab = fetch_json(f"{FRONTEND}/api/vm-lab/status")
    assert isinstance(lab.get("profiles"), list) and len(lab["profiles"]) == 2
    assert isinstance(lab.get("hyperv"), dict)
    assert lab.get("host_network_policy") == "host_unchanged_guest_connected_only_during_installation"
    assert proxy_lab.get("machine_root") == lab.get("machine_root")


def connections_contract() -> None:
    payload = fetch_json(f"{BACKEND}/api/credentials")
    assert isinstance(payload.get("credentials"), dict)
    assert isinstance(payload.get("groups"), dict)


def email_orchestrator_contracts() -> None:
    accounts = fetch_json(f"{BACKEND}/api/email/accounts")
    config = fetch_json(f"{BACKEND}/api/email/automation")
    status = fetch_json(f"{BACKEND}/api/email/automation/status")
    drafts = fetch_json(f"{BACKEND}/api/email/automation/drafts")
    outbox = fetch_json(f"{BACKEND}/api/email/automation/outbox")
    assert isinstance(accounts.get("accounts"), list)
    for account in accounts["accounts"]:
        for secret in ("password", "access_token", "refresh_token", "oauth_client_secret"):
            assert secret not in account
        assert account.get("auth_type") in {"app_password", "oauth2"}
    assert isinstance(config.get("profiles"), dict)
    assert isinstance(config.get("scheduler_enabled"), bool)
    assert isinstance(status.get("selected_accounts"), list)
    assert isinstance(drafts.get("drafts"), list)
    assert isinstance(outbox.get("outbox"), list)


def scheduling_contracts() -> None:
    jobs = fetch_json(f"{BACKEND}/api/cron")
    preview = post_json(f"{BACKEND}/api/cron/preview", {"schedule": "daily at 08:00"})
    assert isinstance(jobs, list)
    assert preview.get("cron") == "0 8 * * *"
    assert len(preview.get("next_runs", [])) == 5


def ssh_contract() -> None:
    connections = fetch_json(f"{BACKEND}/api/ssh")
    assert isinstance(connections, list)
    for connection in connections:
        assert "password" not in connection
        assert "private_key" not in connection


def model_market_contracts() -> None:
    catalog = fetch_json(f"{BACKEND}/api/model-market/catalog?need=research")
    recommendations = fetch_json(
        f"{BACKEND}/api/model-market/recommend?need=research&count=5&distinct_families=true"
    )
    runs = fetch_json(f"{BACKEND}/api/model-market/swarm/runs?limit=1")
    jobs = fetch_json(f"{BACKEND}/api/model-market/swarm/jobs?limit=1")
    evolution = fetch_json(f"{BACKEND}/api/evolution/experiments?limit=1")
    missions = fetch_json(f"{BACKEND}/api/missions?limit=1")
    assert catalog.get("policy") == "passive_real_calls_only"
    assert isinstance(catalog.get("models"), list)
    assert isinstance(recommendations.get("recommendations"), list)
    assert isinstance(runs.get("runs"), list)
    assert isinstance(jobs.get("jobs"), list)
    assert isinstance(evolution.get("experiments"), list)
    assert isinstance(evolution.get("allowed_targets"), dict)
    assert isinstance(missions.get("missions"), list)


def forge_evidence_contracts() -> None:
    scenarios = fetch_json(f"{BACKEND}/api/forge/scenarios")
    leaderboard = fetch_json(f"{BACKEND}/api/forge/arena/leaderboard")
    submissions = fetch_json(f"{BACKEND}/api/forge/arena/submissions?limit=1")
    duels = fetch_json(f"{BACKEND}/api/forge/arena/matches/stats")
    evidence = fetch_json(f"{BACKEND}/api/knowledge/evidence-summary?limit=1")
    assert isinstance(scenarios.get("scenarios"), list)
    assert isinstance(leaderboard.get("systems"), list)
    assert isinstance(submissions.get("submissions"), list)
    assert isinstance(duels.get("matches"), int)
    assert isinstance(duels.get("pending"), int)
    assert isinstance(evidence.get("records"), int)
    assert "average_epistemic_debt" in evidence


def coding_workspace_contracts() -> None:
    overview = fetch_json(f"{BACKEND}/api/coding/overview")
    projects = fetch_json(f"{BACKEND}/api/coding/projects?limit=2")
    jobs = fetch_json(f"{BACKEND}/api/coding/jobs?limit=2")
    hyperv = fetch_json(f"{BACKEND}/api/coding/validation/windows/hyperv")
    proxy_overview = fetch_json(f"{FRONTEND}/api/coding/overview")
    assert isinstance(overview.get("projects"), int)
    assert isinstance(overview.get("languages"), list)
    assert isinstance(overview.get("knowledge", {}).get("sources"), list)
    assert isinstance(projects.get("projects"), list)
    assert isinstance(jobs.get("jobs"), list)
    assert hyperv.get("backend") == "hyperv_powershell_direct"
    assert isinstance(hyperv.get("ready"), bool)
    assert hyperv.get("network_mode") == "offline_native_execution"
    assert "guest_password" not in hyperv
    assert proxy_overview.get("projects") == overview.get("projects")


TESTS: list[tuple[str, Callable[[], None]]] = [
    ("Ollama", ollama_tags),
    ("Sante FastAPI", backend_health),
    ("Contrat OpenAPI", backend_openapi),
    ("Accueil Next.js", lambda: fetch_ok(f"{FRONTEND}/")),
    ("Statut frontend", frontend_status),
    ("Reglages frontend", frontend_settings),
    ("Contrat conversations", conversations_contract),
    ("Contrats projets, taches et notes", organizer_contracts),
    ("Contrats memoires, parametres et sauvegardes", local_data_contracts),
    ("Contrats historique et templates", history_and_templates_contracts),
    ("Contrats facturation, documentation et operations", business_contracts),
    ("Contrats diagnostics et documents", diagnostics_and_documents_contracts),
    ("Contrats agenda", calendar_contracts),
    ("Contrat multi-agents", multi_agents_contract),
    ("Contrat workflows", workflows_contract),
    ("Contrat voix", voice_contract),
    ("Contrats configuration runtime", runtime_config_contracts),
    ("Contrats competences", skills_contracts),
    ("Contrats contenu local", content_contracts),
    ("Bibliotheque et exports Marvin", storage_contracts),
    ("VM Lab et integrite ISO", vm_lab_contracts),
    ("Contrat connexions masquees", connections_contract),
    ("Contrats orchestrateur email", email_orchestrator_contracts),
    ("Contrats planification", scheduling_contracts),
    ("Contrat connexions SSH masquees", ssh_contract),
    ("Contrats Model Market et Research Swarm", model_market_contracts),
    ("Contrats Frontier Arena et Evidence Fabric", forge_evidence_contracts),
    ("Contrats Code Workspace", coding_workspace_contracts),
]


def main() -> int:
    print("\nSMOKE TEST API MARVIN")
    failures = 0
    for name, test in TESTS:
        try:
            test()
            print(f"  [OK] {name}")
        except (AssertionError, KeyError, json.JSONDecodeError, urllib.error.URLError) as exc:
            failures += 1
            print(f"  [ECHEC] {name}: {exc}")
    print(f"Resultat : {len(TESTS) - failures}/{len(TESTS)} contrats OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
