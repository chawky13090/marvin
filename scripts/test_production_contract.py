"""Deterministic regressions for the Production Contract Gate."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import production_contract


def main() -> int:
    report = {
        "tests_executed": True,
        "online_executed": True,
        "steps": [
            {"name": "python_compile", "passed": True},
            {"name": "python_unittest", "passed": True},
        ],
    }
    files = {
        "main.py": "def main(value: str) -> int:\n    return len(value)\n",
        "src/service.py": "def double(value: int) -> int:\n    return value * 2\n",
        "pyproject.toml": "[project]\nname='sample'\nversion='1'\ndependencies=['httpx']\n",
        "requirements.lock": "httpx==0.28.1\nhttpcore==1.0.9\n",
    }
    result = production_contract.evaluate(files, "python", report, request="Crée une application Python")
    assert result["success"] is True
    assert result["profile"] == "production_bundle"
    assert len(result["sbom"]["components"]) == 2
    assert result["sbom"]["bomFormat"] == "CycloneDX"

    untyped = dict(files)
    untyped["src/service.py"] = "def double(value):\n    return value * 2\n"
    rejected = production_contract.evaluate(untyped, "python", report)
    assert rejected["success"] is False
    assert "python_public_api_typed" in {item["name"] for item in rejected["failed_checks"]}

    no_install = production_contract.evaluate(files, "python", {**report, "online_executed": False})
    assert "dependency_installation_proof" in {item["name"] for item in no_install["failed_checks"]}

    npm_files = {
        "main.mjs": "export const value = 1;",
        "package.json": '{"dependencies":{"left-pad":"1.3.0"}}',
        "package-lock.json": '{"lockfileVersion":3,"packages":{"node_modules/left-pad":{"version":"1.3.0","integrity":"sha512-x"}}}',
    }
    npm_report = {"tests_executed": True, "online_executed": True,
                  "steps": [{"name": "node_check", "passed": True}]}
    npm_result = production_contract.evaluate(npm_files, "javascript", npm_report)
    assert npm_result["success"] is True
    assert npm_result["sbom"]["components"][0]["name"] == "left-pad"

    go_files = {
        "main.go": "package main\nfunc Double(value int) int { return value * 2 }\nfunc main() {}\n",
        "go.mod": "module example.com/marvin/sample\n\ngo 1.26\n",
    }
    go_report = {"tests_executed": True, "online_executed": False, "steps": [
        {"name": "gofmt", "passed": True}, {"name": "go_vet", "passed": True},
        {"name": "go_test", "passed": True},
    ]}
    go_result = production_contract.evaluate(go_files, "go", go_report)
    assert go_result["success"] is True
    assert go_result["external_dependencies"] is False

    print("Production Contract Gate OK - preuves, typage public, installation et SBOM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
