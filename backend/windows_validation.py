"""Deterministic Windows validation routing; cross-build is never native execution."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import windows_test_runner
import hyperv_test_runner


_DESKTOP_MARKERS = ("usewpf", "usewindowsforms", "winui", "maui", "electron", "tauri")
_INSTALLER_SUFFIXES = {".msi", ".msix", ".appx", ".appxbundle"}
_DRIVER_SUFFIXES = {".inf", ".sys", ".cat"}


def route(files: list[str] | dict[str, Any], request: str = "") -> dict[str, Any]:
    paths = [str(item).replace("\\", "/") for item in (files.keys() if isinstance(files, dict) else files)]
    lowered = " ".join(paths + [request]).casefold()
    suffixes = {Path(path).suffix.casefold() for path in paths}
    sandbox = windows_test_runner.status()
    hyperv = hyperv_test_runner.status()
    if suffixes & _DRIVER_SUFFIXES or re.search(r"\b(driver|pilote|kernel|noyau)\b", lowered):
        return _result("hyperv_checkpoint_vm", "driver", False,
                       "Pilotes et code noyau exigent une VM Hyper-V dédiée avec checkpoint et redémarrage.", sandbox, hyperv)
    installer_executable = any(
        Path(path).suffix.casefold() == ".exe"
        and re.search(r"(?i)(setup|install|uninstall|bootstrap)", Path(path).stem)
        for path in paths
    )
    if suffixes & _INSTALLER_SUFFIXES or installer_executable or re.search(r"\b(msi|msix|installateur|installer)\b", lowered):
        return _result("hyperv_checkpoint_vm", "installer", False,
                       "Installation, désinstallation et rollback exigent une VM Windows persistante à checkpoint.", sandbox, hyperv)
    if any(marker in lowered for marker in _DESKTOP_MARKERS) or re.search(r"\b(gui|desktop|win32|wpf|winforms)\b", lowered):
        return _result("windows_gui_vm", "desktop", False,
                       "Une application graphique exige une session interactive, des assertions UI et des captures.", sandbox, hyperv)
    if suffixes and suffixes.issubset({".ps1", ".psm1", ".psd1", ".json", ".md"}):
        return _result("windows_sandbox_powershell", "powershell", bool(sandbox["available"]),
                       "Parser, PSScriptAnalyzer et Pester sont exécutés dans Windows Sandbox.", sandbox, hyperv)
    return _result("windows_cli_vm", "cli_or_service", bool(hyperv["ready"]),
                   "Le build Windows doit être suivi d'une exécution et de tests natifs dans une VM Windows jetable.", sandbox, hyperv)


def _result(backend: str, workload: str, available: bool, reason: str,
            sandbox: dict[str, Any], hyperv: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": "windows", "workload": workload, "required_backend": backend,
        "certification_available": available, "reason": reason,
        "requirements": {
            "native_execution": True, "tests_executed": True,
            "internet_during_dependency_stage": True, "private_networks_blocked": True,
            "fresh_checkpoint": True,
            "evidence": ["environment", "build", "tests", "exit_codes", "artifacts"],
        },
        "sandbox": sandbox,
        "hyperv": hyperv,
        "production_ready_rule": "production_ready reste false tant que le backend requis n'a pas exécuté le livrable et ses tests.",
    }
