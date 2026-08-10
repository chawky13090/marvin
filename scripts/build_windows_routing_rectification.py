"""Construit le rectificatif du diagnostic de routage Forge sans appeler de LLM.

Les contrats sont évalués contre les blobs du commit historique de campagne. Les résultats
de routage ne sont lus qu'après le gel et la vérification de la matrice de capacités.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_COMMIT = "e7df13dfcf9678cf987f451bb18ab78eeba2926b"
CONTRACT_ROOT = ROOT / "benchmarks" / "windows-operator" / "v1.1"
CAMPAIGN_ROOT = ROOT / "benchmarks" / "windows-operator" / "campaigns" / "baseline-20260809"
ORIGINAL_REPORT = CAMPAIGN_ROOT / "windows-task-acceptance-report.json"
PRESERVED_REPORT = CAMPAIGN_ROOT / "windows-task-acceptance-report.v1.0-original.json"
CONTRACT_OUTPUT = CONTRACT_ROOT / "routing-capability-contracts-retrospective-v1.json"
RECTIFICATION_OUTPUT = CAMPAIGN_ROOT / "windows-task-routing-rectification-v1.json"

HISTORICAL_PATHS = {
    "tools.py": "backend/tools.py",
    "capability_discovery.py": "backend/capability_discovery.py",
    "capability_catalog.py": "backend/capability_catalog.py",
    "intent_corpus": "benchmarks/windows-operator/v1.1/intent-corpus.json",
}
ARTIFACT_SOURCE_PATHS = {
    "agent.py": "backend/agent.py",
    "agent_tool_step.py": "backend/agent_tool_step.py",
    "agent_tool_selection.py": "backend/agent_tool_selection.py",
    "capability_catalog.py": "backend/capability_catalog.py",
    "capability_discovery.py": "backend/capability_discovery.py",
    "tools.py": "backend/tools.py",
    "windows_task.py": "backend/windows_task.py",
    "routing_runner.py": "scripts/run_windows_operator_routing_baseline.py",
}

# Ces contrats décrivent les capacités demandées par le corpus, pas les sélections observées.
# Une action non nulle signifie que le nom seul est compatible, mais que la campagne historique
# ne permet pas de prouver l'action réellement produite par le modèle.
CAPABILITY_CONTRACTS: dict[str, dict[str, Any]] = {
    "process.inventory": {
        "family": "process_inventory",
        "rationale": "La demande porte sur la lecture de l'inventaire des processus, sans mutation.",
        "tools": [
            {"name": "pc_process_list", "action": None, "role": "terminal"},
            {"name": "windows_task", "action": "process.list", "role": "terminal"},
        ],
    },
    "process.stop": {
        "family": "process_action",
        "rationale": "La capacité attendue doit arrêter un processus puis permettre sa vérification.",
        "tools": [
            {"name": "pc_process_kill", "action": None, "role": "terminal"},
            {"name": "windows_task", "action": "process.stop", "role": "terminal"},
        ],
    },
    "application.launch": {
        "family": "application_launch",
        "rationale": "La demande lance une application installée, sans interaction visuelle imposée.",
        "tools": [
            {"name": "pc_app_launch", "action": None, "role": "terminal"},
            {"name": "windows_task", "action": "application.launch", "role": "terminal"},
        ],
    },
    "service.change_state": {
        "family": "windows_services",
        "rationale": "Les intentions modifient l'état d'un service; service.list ne suffit pas.",
        "tools": [
            {"name": "win_service_action", "action": "start|stop|restart", "role": "terminal"},
        ],
    },
    "software.install": {
        "family": "software_management",
        "rationale": "Toutes les intentions du corpus installent un logiciel; la résolution du paquet est une étape préparatoire valide.",
        "tools": [
            {"name": "winget_search", "action": None, "role": "preparatory"},
            {"name": "winget_list_installed", "action": None, "role": "preparatory"},
            {"name": "winget_install", "action": None, "role": "terminal"},
        ],
    },
    "filesystem.search_by_name": {
        "family": "file_discovery",
        "rationale": "Les intentions recherchent un nom ou motif sur le PC, pas le contenu interne d'un document.",
        "tools": [
            {"name": "system_search", "action": None, "role": "terminal"},
            {"name": "file_find", "action": None, "role": "terminal"},
            {"name": "unified_search", "action": None, "role": "broader_valid"},
        ],
    },
    "filesystem.move": {
        "family": "file_mutation",
        "rationale": "Toutes les intentions déplacent une source vers une destination; copie et renommage seuls ne satisfont pas le contrat.",
        "tools": [
            {
                "name": "file_find",
                "action": None,
                "role": "preparatory",
                "condition": "source_path_unresolved",
            },
            {"name": "file_move", "action": None, "role": "terminal"},
        ],
    },
    "system.diagnose": {
        "family": "system_diagnostics",
        "rationale": "Un rapport global ou une première collecte de preuve système constitue un premier appel recevable.",
        "tools": [
            {"name": "win_system_report", "action": None, "role": "terminal"},
            {"name": "pc_system_info", "action": None, "role": "evidence"},
            {"name": "pc_hardware_specs", "action": None, "role": "evidence"},
            {"name": "pc_event_log_errors", "action": None, "role": "evidence"},
            {"name": "pc_disk_smart_health", "action": None, "role": "evidence"},
        ],
    },
    "network.diagnose": {
        "family": "network_diagnostics",
        "rationale": "Le diagnostic peut commencer par le rapport composite ou par une preuve réseau ciblée pertinente.",
        "tools": [
            {"name": "net_route_diagnostics", "action": None, "role": "terminal"},
            {"name": "net_dns_lookup", "action": None, "role": "evidence"},
            {"name": "net_ping", "action": None, "role": "evidence"},
            {"name": "net_traceroute", "action": None, "role": "evidence"},
            {"name": "windows_task", "action": "network.status", "role": "evidence"},
        ],
    },
    "security.firewall.inspect": {
        "family": "security_posture",
        "rationale": "Les intentions lisent l'état du pare-feu; aucune action d'activation ou désactivation n'est recevable.",
        "tools": [
            {"name": "win_firewall_status", "action": None, "role": "terminal"},
            {"name": "os_firewall", "action": "status", "role": "terminal"},
            {"name": "windows_task", "action": "security.firewall.status", "role": "terminal"},
        ],
    },
    "desktop.visual_interaction": {
        "family": "desktop_observation",
        "rationale": "Les intentions exigent observation, UIA, capture, clic ou saisie sur une interface réellement visible.",
        "tools": [
            {
                "name": "computer_control",
                "action": "observe|screenshot|click|type|focus|verify",
                "role": "terminal",
            },
            {"name": "pc_gui_read", "action": None, "role": "evidence"},
        ],
        "explicit_rejections": ["windows_task"],
    },
    "text.only": {
        "family": "text_only_command",
        "rationale": "L'utilisateur demande explicitement du texte sans aucune exécution.",
        "tools": [],
        "explicit_rejections": ["windows_task", "computer_control", "pc_run_powershell"],
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob(path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{HISTORICAL_COMMIT}:{path}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def _read_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Objet JSON attendu : {label}")
    return payload


def _verify_artifact_sources(artifact: dict[str, Any], label: str) -> dict[str, Any]:
    """Compare les empreintes de campagne aux blobs du commit de reference.

    Une divergence est conservee comme limite de provenance et ne doit jamais etre
    transformee en fausse preuve. Les contrats restent, eux, integralement derives du commit.
    """
    recorded = artifact.get("source_hashes")
    if not isinstance(recorded, dict) or set(recorded) != set(ARTIFACT_SOURCE_PATHS):
        raise ValueError(f"Inventaire de sources incomplet : {label}")
    comparison: dict[str, Any] = {}
    exact = 0
    for source_name, repository_path in ARTIFACT_SOURCE_PATHS.items():
        observed = _sha256(_git_blob(repository_path))
        expected = str(recorded[source_name])
        matches = observed == expected
        exact += int(matches)
        comparison[source_name] = {
            "path": repository_path,
            "recorded_sha256": expected,
            "reference_commit_sha256": observed,
            "matches_reference_commit": matches,
        }

    corpus_hash = _sha256(_git_blob(HISTORICAL_PATHS["intent_corpus"]))
    if str(artifact.get("corpus_sha256")) != corpus_hash:
        raise ValueError(f"Corpus historique incoherent : {label}")
    return {
        "historical_commit": HISTORICAL_COMMIT,
        "sources": comparison,
        "exact_matches": exact,
        "source_count": len(comparison),
        "corpus_sha256": corpus_hash,
        "corpus_matches_reference_commit": True,
        "provenance_complete": exact == len(comparison),
        "limitation": (
            None
            if exact == len(comparison)
            else "Certaines empreintes de campagne ne correspondent a aucun blob du commit de reference; elles sont conservees sans sur-declaration."
        ),
    }


def _extract_tool_specs(source: bytes) -> dict[str, dict[str, Any]]:
    tree = ast.parse(source.decode("utf-8"))
    specs: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_t"
            and len(node.args) >= 2
        ):
            continue
        try:
            name = ast.literal_eval(node.args[0])
            description = ast.literal_eval(node.args[1])
            properties = ast.literal_eval(node.args[2]) if len(node.args) >= 3 else {}
            required = ast.literal_eval(node.args[3]) if len(node.args) >= 4 else []
        except (TypeError, ValueError, SyntaxError):
            continue
        if isinstance(name, str) and isinstance(description, str):
            specs[name] = {
                "description": description,
                "properties": properties if isinstance(properties, dict) else {},
                "required": required if isinstance(required, list) else [],
                "source_line": int(node.lineno),
            }
    if len(specs) != 364:
        raise ValueError(f"Catalogue historique incomplet : {len(specs)}/364 outils")
    return specs


def _action_enum(spec: dict[str, Any]) -> set[str]:
    action = spec.get("properties", {}).get("action", {})
    values = action.get("enum", []) if isinstance(action, dict) else []
    return {str(item) for item in values}


def _action_supported(spec: dict[str, Any], expected: str | None) -> bool:
    if expected is None:
        return True
    available = _action_enum(spec)
    return all(part in available for part in expected.split("|"))


def build_contract_payload() -> dict[str, Any]:
    blobs = {name: _git_blob(path) for name, path in HISTORICAL_PATHS.items()}
    specs = _extract_tool_specs(blobs["tools.py"])
    corpus = _read_json_bytes(blobs["intent_corpus"], "intent-corpus")
    by_family = {value["family"]: key for key, value in CAPABILITY_CONTRACTS.items()}
    if set(by_family) != {str(item["family"]) for item in corpus["items"]}:
        raise ValueError("Les contrats ne couvrent pas exactement les familles du corpus.")

    contracts: dict[str, Any] = {}
    for capability_id, definition in CAPABILITY_CONTRACTS.items():
        tools: list[dict[str, Any]] = []
        for accepted in definition.get("tools", []):
            name = str(accepted["name"])
            if name not in specs:
                raise ValueError(f"Outil absent du snapshot historique : {name}")
            if not _action_supported(specs[name], accepted.get("action")):
                raise ValueError(
                    f"Action non supportée par le snapshot : {name}/{accepted.get('action')}"
                )
            tools.append(
                {
                    **accepted,
                    "catalog_description": specs[name]["description"],
                    "catalog_source_line": specs[name]["source_line"],
                    "catalog_spec_sha256": _sha256(
                        json.dumps(specs[name], ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ),
                }
            )
        rejected = [str(name) for name in definition.get("explicit_rejections", [])]
        if any(name not in specs for name in rejected):
            raise ValueError(f"Rejet explicite absent du catalogue : {rejected}")
        contracts[capability_id] = {
            "family": definition["family"],
            "rationale": definition["rationale"],
            "accepted": tools,
            "explicit_rejections": rejected,
        }

    matrix = [
        {
            "intent_id": item["id"],
            "split": item["split"],
            "family": item["family"],
            "capability_id": by_family[item["family"]],
        }
        for item in corpus["items"]
    ]
    payload = {
        "schema": "marvin.windows-routing-capability-contracts/1.0",
        "status": "frozen_retrospective_before_rescoring",
        "methodology": {
            "historical_commit": HISTORICAL_COMMIT,
            "retrospective": True,
            "routing_results_used_to_build_matrix": False,
            "scope": "compatibilité du premier nom d'outil uniquement",
            "action_limitation": (
                "Les événements historiques ne conservent pas les arguments. Une action "
                "déclarée reste compatible mais non vérifiée."
            ),
        },
        "historical_sources": {
            name: {"path": HISTORICAL_PATHS[name], "sha256": _sha256(data)}
            for name, data in blobs.items()
        },
        "catalog_tool_count": len(specs),
        "contracts": contracts,
        "intent_matrix": matrix,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    payload["matrix_sha256"] = _sha256(canonical)
    return payload


def _classify_row(
    row: dict[str, Any],
    matrix_by_intent: dict[str, dict[str, Any]],
    contracts: dict[str, dict[str, Any]],
    catalog_names: set[str],
) -> dict[str, Any]:
    matrix = matrix_by_intent[str(row["intent_id"])]
    contract = contracts[matrix["capability_id"]]
    accepted = {item["name"]: item for item in contract["accepted"]}
    selected = [str(name) for name in row.get("selected_tools", [])]
    if not selected:
        classification = "compatible" if not accepted else "missing_selection"
        chosen: dict[str, Any] | None = None
    else:
        name = selected[0]
        chosen = accepted.get(name)
        if name not in catalog_names:
            classification = "nonexistent_tool"
        elif chosen is not None and chosen.get("action"):
            classification = "compatible_name_action_unverified"
        elif chosen is not None and chosen.get("condition"):
            classification = "compatible_name_condition_unverified"
        elif chosen is not None:
            classification = "compatible"
        else:
            classification = "incompatible_tool"
    return {
        "intent_id": row["intent_id"],
        "run": row["run"],
        "family": row["family"],
        "selected_tools": selected,
        "capability_id": matrix["capability_id"],
        "classification": classification,
        "accepted_role": chosen.get("role") if chosen else None,
        "required_action": chosen.get("action") if chosen else None,
        "required_condition": chosen.get("condition") if chosen else None,
        "historical_passed": bool(row.get("passed")),
    }


def _summarize_rectified(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row["classification"] for row in rows)
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_family[row["family"]][row["classification"]] += 1
    compatible = (
        counts["compatible"]
        + counts["compatible_name_action_unverified"]
        + counts["compatible_name_condition_unverified"]
    )
    total = len(rows)
    nonexistent_names = Counter(
        row["selected_tools"][0]
        for row in rows
        if row["classification"] == "nonexistent_tool" and row["selected_tools"]
    )
    incompatible_names = Counter(
        row["selected_tools"][0]
        for row in rows
        if row["classification"] == "incompatible_tool" and row["selected_tools"]
    )
    return {
        "runs": total,
        "compatible_tool_name_runs": compatible,
        "compatible_tool_name_rate": round(compatible / total, 4) if total else 0,
        "compatible_without_action_discriminator_runs": counts["compatible"],
        "action_unverified_runs": counts["compatible_name_action_unverified"],
        "condition_unverified_runs": counts["compatible_name_condition_unverified"],
        "nonexistent_tool_runs": counts["nonexistent_tool"],
        "nonexistent_tool_names": dict(sorted(nonexistent_names.items())),
        "incompatible_tool_runs": counts["incompatible_tool"],
        "incompatible_tool_names": dict(sorted(incompatible_names.items())),
        "missing_selection_runs": counts["missing_selection"],
        "by_family": {
            family: {
                **dict(counter),
                "runs": sum(counter.values()),
                "compatible_tool_name_rate": round(
                    (
                        counter["compatible"]
                        + counter["compatible_name_action_unverified"]
                        + counter["compatible_name_condition_unverified"]
                    )
                    / sum(counter.values()),
                    4,
                ),
            }
            for family, counter in sorted(by_family.items())
        },
    }


def build_rectification(contract_payload: dict[str, Any]) -> dict[str, Any]:
    specs = _extract_tool_specs(_git_blob(HISTORICAL_PATHS["tools.py"]))
    matrix = {item["intent_id"]: item for item in contract_payload["intent_matrix"]}
    contracts = contract_payload["contracts"]
    artifact_names = {
        "development": "routing-windows-task-normative-candidate.json",
        "holdout": "routing-windows-task-holdout-source-closed.json",
    }
    splits: dict[str, Any] = {}
    for split, name in artifact_names.items():
        artifact_path = CAMPAIGN_ROOT / name
        artifact = _read_json_bytes(artifact_path.read_bytes(), name)
        if artifact.get("routing_policy") != "windows_task":
            raise ValueError(f"Politique de routage inattendue : {name}")
        source_verification = _verify_artifact_sources(artifact, name)
        classified = [
            _classify_row(row, matrix, contracts, set(specs))
            for row in artifact.get("results", [])
        ]
        splits[split] = {
            "artifact": name,
            "artifact_sha256": _sha256(artifact_path.read_bytes()),
            "source_verification": source_verification,
            "historical_adoption_summary": artifact["summary"],
            "retrospective_tool_name_compatibility": _summarize_rectified(classified),
            "results": classified,
        }
    return {
        "schema": "marvin.windows-routing-rectification/1.0",
        "status": "retrospective_corrected_score",
        "scope": "routing_diagnostic_only",
        "historical_routing_policy": "windows_task",
        "e2e_verdict_unchanged": True,
        "independent_validation_score": None,
        "independent_validation_required_after_product_change": True,
        "historical_commit": HISTORICAL_COMMIT,
        "capability_matrix": str(CONTRACT_OUTPUT.relative_to(ROOT)).replace("\\", "/"),
        "capability_matrix_sha256": contract_payload["matrix_sha256"],
        "interpretation": (
            "Le score historique mesure l'adoption de l'outil privilégié par la politique "
            "windows_task. Le score corrigé mesure seulement la compatibilité du premier nom "
            "d'outil; les arguments, actions et résultats ne sont pas présents dans cet artefact."
        ),
        "splits": splits,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _mark_primary_report(original_bytes: bytes, rectification: dict[str, Any]) -> dict[str, Any]:
    report = _read_json_bytes(original_bytes, "windows-task-acceptance-report")
    report["interpretation_caveat"] = {
        "status": "superseded_for_general_routing_only",
        "routing_policy": "windows_task",
        "original_report_sha256": _sha256(original_bytes),
        "preserved_original": PRESERVED_REPORT.name,
        "superseded_by": RECTIFICATION_OUTPUT.name,
        "e2e_verdict_unchanged": True,
    }
    return report


def generate() -> tuple[dict[str, Any], dict[str, Any]]:
    contract_payload = build_contract_payload()
    rectification = build_rectification(contract_payload)
    original_bytes = ORIGINAL_REPORT.read_bytes()
    if not PRESERVED_REPORT.exists():
        PRESERVED_REPORT.write_bytes(original_bytes)
    elif PRESERVED_REPORT.read_bytes() != original_bytes and "interpretation_caveat" not in _read_json_bytes(original_bytes, "primary"):
        raise ValueError("La copie originale existe mais ne correspond pas au rapport primaire.")
    preserved_bytes = PRESERVED_REPORT.read_bytes()
    rectification["original_acceptance_report_sha256"] = _sha256(preserved_bytes)
    _atomic_json(CONTRACT_OUTPUT, contract_payload)
    _atomic_json(RECTIFICATION_OUTPUT, rectification)
    _atomic_json(ORIGINAL_REPORT, _mark_primary_report(preserved_bytes, rectification))
    return contract_payload, rectification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    contract_payload, rectification = generate()
    print(
        json.dumps(
            {
                "matrix": str(CONTRACT_OUTPUT),
                "matrix_sha256": contract_payload["matrix_sha256"],
                "rectification": str(RECTIFICATION_OUTPUT),
                "development": rectification["splits"]["development"]["retrospective_tool_name_compatibility"],
                "holdout": rectification["splits"]["holdout"]["retrospective_tool_name_compatibility"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
