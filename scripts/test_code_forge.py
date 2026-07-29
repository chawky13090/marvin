"""Régressions Code Forge sans appel cloud et sans exécution du code généré."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import adaptive_team
import audit
import code_forge
import cortex


async def exercise_pipeline() -> None:
    reviews = (
        '{"score":8,"verdict":"corrigeable","issues":[{"severity":"high",'
        '"problem":"gestion erreur absente","correction":"ajouter try/except"}]}',
        '{"score":9,"verdict":"sûr","issues":[]}',
    )
    calls = [
        {"ok": True, "model": "architect:cloud", "family": "architect", "answer": "Cible Python 3.12. Entrée: chemin. Rollback: aucun état modifié."},
        {"ok": True, "model": "coder:cloud", "family": "coder", "answer": "```python file=main.py\nprint('initial')\n```\n```python file=src/helper.py\ndef value() -> int: return 42\n```\n```toml file=pyproject.toml\n[project]\nname = 'sample'\nversion = '1.0.0'\ndependencies = []\n```"},
        {"ok": True, "model": "review-a:cloud", "family": "review-a", "answer": reviews[0]},
        {"ok": True, "model": "review-b:cloud", "family": "review-b", "answer": reviews[1]},
        {"ok": True, "model": "repair:cloud", "family": "repair", "answer": "```python\nfrom __future__ import annotations\n\ndef main() -> int:\n    print('ok')\n    return 0\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n```"},
        {"ok": True, "model": "review-a:cloud", "family": "review-a", "answer": '{"score":9,"verdict":"prêt","issues":[]}'},
        {"ok": True, "model": "review-b:cloud", "family": "review-b", "answer": "```python\nimport unittest\nimport main\n\nclass TestMain(unittest.TestCase):\n    def test_main(self):\n        self.assertEqual(main.main(), 0)\n\nif __name__ == '__main__':\n    unittest.main()\n```"},
        {"ok": True, "model": "review-a:cloud", "family": "review-a", "answer": '{"score":9,"verdict":"prêt après tests","issues":[]}'},
    ]
    markets = [
        {"model": "architect:cloud", "family": "architect"},
        {"model": "coder:cloud", "family": "coder"},
        {"model": "review-a:cloud", "family": "review-a"},
        {"model": "review-b:cloud", "family": "review-b"},
    ]
    with (
        patch.object(code_forge, "validate_runtime", return_value=None),
        patch.object(code_forge.model_market, "recommend", return_value=markets),
        patch.object(code_forge.model_market, "catalog", return_value={"models": markets}),
        patch.object(
            code_forge.engineering_radar,
            "ensure_for_request",
            new=AsyncMock(return_value={
                "languages": ["python"],
                "context": "BEGIN_UNTRUSTED_OFFICIAL_DOCUMENTATION [python-whatsnew]\n"
                           "Official Python release notes\n"
                           "END_UNTRUSTED_OFFICIAL_DOCUMENTATION [python-whatsnew]",
                "sources": [{
                    "id": "python-whatsnew",
                    "title": "Python release notes",
                    "url": "https://docs.python.org/3/whatsnew/",
                    "content_sha256": "abc123",
                    "freshness": "fresh",
                }],
                "source_count": 1, "available": True,
            }),
        ),
        patch.object(code_forge, "_call", new=AsyncMock(side_effect=calls)) as call_model,
        patch.object(
            code_forge.test_forge,
            "execute",
            return_value={
                "success": True,
                "production_ready": True,
                "tests_executed": True,
                "online_executed": False,
                "steps": [
                    {"name": "python_compile", "passed": True, "exit_code": 0},
                    {"name": "python_unittest", "passed": True, "exit_code": 0},
                ],
                "isolation": {"network": "none", "read_only_rootfs": True},
            },
        ) as test_execute,
    ):
        result = await code_forge.execute("Crée un script Python complet qui affiche ok.")
    assert result["success"] is True
    assert result["generation"]["provider"] == "ollama_cloud"
    assert result["generation"]["workflow_cloud_only"] is True
    assert result["language"] == "python"
    assert result["validation"]["syntax_valid"] is True
    assert result["critical_issues"] == 0
    assert result["final_review"]["score"] == 9
    assert result["test_report"]["production_ready"] is True
    assert result["production_contract"]["success"] is True
    assert "unittest" in result["test_code"]
    assert "raise SystemExit(main())" in result["code"]
    assert result["bundle"]["file_count"] == 3
    assert "src/helper.py" in result["files"]
    assert test_execute.call_args.kwargs["files"]["src/helper.py"].startswith("def value")
    assert len(result["reviews"]) == 2
    assert result["engineering_radar"]["languages"] == ["python"]
    assert "## Documentation technique consultée" in result["answer"]
    assert "https://docs.python.org/3/whatsnew/" in result["answer"]
    assert "UNTRUSTED_OFFICIAL_DOCUMENTATION" in call_model.await_args_list[0].args[2]


def main() -> int:
    assert code_forge.requires_online_install_test("Installer un service Debian") is True
    assert code_forge.requires_online_install_test("Projet Python sans dépendance externe") is False
    assert code_forge.requires_online_install_test("Python project with no external dependencies") is False
    assert code_forge.should_activate("Crée un script d'installation Bash sécurisé.") is True
    assert code_forge.should_activate("Explique-moi simplement Bash.") is False
    assert code_forge.should_create_coding_mission(
        "Construis une application complète multi-fichiers pour Windows et Linux."
    ) is True
    assert code_forge.should_create_coding_mission("Crée un petit script Python.") is False
    code, language = code_forge.extract_code("Texte\n```python\nprint('ok')\n```\n")
    assert code == "print('ok')" and language == "python"
    assert code_forge.detect_language("script Python", code) == "python"
    assert code_forge.validate_code("x = 1\nprint(x)\n", "python")["success"] is True
    unlocked = code_forge.validate_deliverable(
        "print('ok')\n",
        "python",
        files={
            "pyproject.toml": "[project]\nname='x'\nversion='1'\ndependencies=['httpx']\n"
        },
    )
    assert unlocked["success"] is False
    assert "python_dependencies_locked" in {
        item["name"] for item in unlocked["failed_checks"]
    }
    invalid = code_forge.validate_code("def broken(:\n    pass\n", "python")
    assert invalid["success"] is False
    assert invalid["syntax_valid"] is False
    placeholder = code_forge.validate_code("# TODO reste du code\nprint('x')\n", "python")
    assert placeholder["success"] is False
    powershell = code_forge.validate_code(
        'Set-StrictMode -Version Latest\n$ErrorActionPreference = "Stop"\nWrite-Output "OK"\n',
        "powershell",
    )
    syntax_check = next(item for item in powershell["checks"] if item["name"] == "syntax")
    if syntax_check["available"]:
        assert powershell["syntax_valid"] is True
    broken_bash = code_forge.validate_code(
        "#!/usr/bin/env bash\nset -euo pipefail\nDOMAIN=example.test\n"
        "echo \"Password=${DB_PASS}\"\necho \"${TOTP_SECRET}\"\napt-get upgrade -y\n",
        "bash",
        request="Script d'installation Zabbix",
    )
    failed_names = {item["name"] for item in broken_bash["failed_checks"]}
    assert "bash_defined_variables" in failed_names
    assert "no_secret_output" in failed_names
    assert "no_unbounded_system_upgrade" in failed_names
    assert "privilege_check" in failed_names
    destructive_installer = code_forge.validate_code(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        "[[ $(id -u) -eq 0 ]] || exit 2\n"
        "apt-get install -y --allow-remove-essential nginx\n"
        "ufw --force enable\nufw default deny incoming\nufw allow OpenSSH\n"
        "ufw status | grep -q 'Default: deny (incoming)'\n",
        "bash",
        request="Script d'installation serveur",
    )
    destructive_failures = {item["name"] for item in destructive_installer["failed_checks"]}
    assert "no_remove_essential_packages" in destructive_failures
    assert "firewall_rules_before_enable" in destructive_failures
    assert "ufw_default_status_verbose" in destructive_failures
    secret_argument = code_forge.validate_code(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\nDB_PASSWORD=x\n"
        "if [[ ${EUID} -ne 0 ]]; then exit 2; fi\n"
        "mysql -u zabbix -p\"${DB_PASSWORD}\" zabbix -e 'SELECT 1'\n",
        "bash",
        request="Script d'installation Zabbix",
    )
    assert "no_secret_process_arguments" in {
        item["name"] for item in secret_argument["failed_checks"]
    }
    optional_env = code_forge.validate_code(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        "if [[ -n \"${ZBX_DB_PASSWORD:-}\" ]]; then DB_PASSWORD=\"${ZBX_DB_PASSWORD}\"; fi\n"
        "echo \"ZBX_DB_PASSWORD peut être fourni par l'environnement\"\n"
        "if [[ ${EUID} -ne 0 ]]; then exit 2; fi\n",
        "bash",
        request="Script d'installation Zabbix",
    )
    optional_failed = {item["name"] for item in optional_env["failed_checks"]}
    assert "bash_defined_variables" not in optional_failed
    assert "no_secret_output" not in optional_failed
    normalized = code_forge._normalize_review(
        '{"score":10,"verdict":"refusé","issues":[{"severity":"critical",'
        '"problem":"cassé","correction":"corriger"}]}'
    )
    assert normalized["score"] == 4
    calibrated = code_forge._normalize_issue_decisions(
        {
            "decisions": [
                {
                    "index": 0,
                    "valid": True,
                    "severity": "high",
                    "category": "maintainability",
                    "reproduced": False,
                    "reason": "Risque futur non reproduit.",
                },
                {
                    "index": 1,
                    "valid": True,
                    "severity": "critical",
                    "category": "security",
                    "reproduced": False,
                    "reason": "Injection de commande concrète.",
                },
            ]
        },
        [
            {"severity": "high", "problem": "choix Unicode futur"},
            {"severity": "high", "problem": "injection"},
        ],
        [0, 1],
    )
    assert calibrated[0]["severity"] == "medium"
    assert calibrated[1]["severity"] == "high"
    assert calibrated[1]["category"] == "security"

    compiled = cortex.compile_contract("Crée un script d'installation Bash sécurisé et complet.")
    assert compiled["forced_tools"] == ["ai_adaptive_team"]
    direct = cortex.compile_contract("Crée un script Python complet qui lit un fichier CSV local.")
    assert direct["forced_tools"] == ["ai_code_forge"]
    assert adaptive_team.plan(
        "Recherche la documentation actuelle puis crée un script Bash d'installation sécurisé."
    )["pipeline"] == ["research_swarm", "code_forge"]
    with tempfile.TemporaryDirectory() as temporary:
        old_path = audit._AUDIT_PATH
        try:
            audit._AUDIT_PATH = str(Path(temporary) / "audit.jsonl")
            audit.log_action("ai_code_forge", {}, {"success": False, "final_review": {"verdict": "Refusé"}})
            entry = json.loads(Path(audit._AUDIT_PATH).read_text(encoding="utf-8"))
            assert entry["ok"] is False
            assert entry["error"] == "Refusé"
        finally:
            audit._AUDIT_PATH = old_path
    asyncio.run(exercise_pipeline())
    print("Code Forge OK - activation, double revue, réparation et validation syntaxique.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
