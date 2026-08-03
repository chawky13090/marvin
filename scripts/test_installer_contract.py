"""Contrat statique de l'installation Windows portable, sans mutation système."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    installer = (ROOT / "INSTALLER-NOUVEAU-PC.bat").read_text(encoding="utf-8")
    legacy_installer = (ROOT / "install.ps1").read_text(encoding="utf-8")
    cleanup = (ROOT / "scripts" / "cleanup-vm-diagnostic.ps1").read_text(encoding="utf-8")
    model_plan = (ROOT / "scripts" / "plan_local_models.py").read_text(encoding="utf-8")
    verifier = (ROOT / "VERIFIER-INSTALLATION.bat").read_text(encoding="utf-8")
    report = (ROOT / "scripts" / "write-install-report.ps1").read_text(encoding="utf-8")
    autostart = (ROOT / "scripts" / "install-marvin-autostart.ps1").read_text(encoding="utf-8")
    libreoffice = (ROOT / "scripts" / "manage-libreoffice.ps1").read_text(encoding="utf-8")
    libreoffice_manifest = (ROOT / "scripts" / "libreoffice-component.json").read_text(encoding="utf-8")
    python_resolver = (ROOT / "scripts" / "resolve-python-runtime.ps1").read_text(encoding="utf-8")
    python_migration = (ROOT / "scripts" / "migrate-python-runtime.ps1").read_text(encoding="utf-8")
    context_resolver = (ROOT / "scripts" / "resolve-ollama-context-profile.ps1").read_text(encoding="utf-8")
    starter = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "npm ci" in installer
    assert "resolve-python-runtime.ps1" in installer
    assert '"!MARVIN_PYTHON!" -m venv .venv' in installer
    assert "python -m venv .venv" not in installer
    assert "nomic-embed-text" in installer
    assert "SetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH','32768','User')" not in installer
    assert "calibrate-ollama-context.py --verify" in installer
    assert "ollama-context-profile.json" in installer
    assert "migrate-ollama-context-profile.ps1" in installer
    assert "Les modeles Cloud ne recoivent aucun override de contexte" in installer
    assert "[1/9]" in installer
    assert "install-desktop-avatar.ps1" in installer
    assert "plan_local_models.py" in installer
    assert "qwen2.5:7b" not in installer
    assert "llava-phi3" not in installer
    assert "write-install-report.ps1" in installer
    assert "secrets DPAPI restent lies au compte Windows" in installer
    assert "manage-libreoffice.ps1" in installer
    assert "-Action Ensure" in installer
    assert "INSTALLER-NOUVEAU-PC.bat" in legacy_installer
    assert "VOTRE_USERNAME" not in legacy_installer
    assert "$PSScriptRoot" in cleanup
    assert "C:\\Users\\Chawb" not in cleanup
    assert "local_model_policy.recommend" in model_plan
    assert "Docker introuvable - Test Forge production indisponible" not in verifier
    assert "write-install-report.ps1" in verifier
    assert "install-capabilities.json" in report
    assert "libreoffice_document_validation" in report
    assert "inspect-secret-lifecycle.py" in report
    assert "secret_portability" in report
    assert "reauthentication_required" in report
    assert "LibreOffice\\program\\soffice.com" in report
    assert "TheDocumentFoundation.LibreOffice" in libreoffice_manifest
    assert "--version" in libreoffice and "--silent" in libreoffice
    assert "ShouldProcess" in libreoffice
    assert "-Action Verify" in verifier
    assert "Microsoft-Hyper-V-All" in report
    assert "Containers-DisposableClientVM" in report
    assert "Marvin-Debian13-TestForge" in report
    assert "Marvin-Windows11-TestForge" in report
    assert "overall = if ($CoreReady)" in report
    assert "python_runtime.inspect_runtime" in report
    assert "codex-runtimes" in python_resolver
    assert "3.12.0" in python_resolver and "3.14.0" in python_resolver
    assert "ShouldProcess" in python_migration
    assert ".venv.rollback-" in python_migration
    assert "pip', 'check'" in python_migration
    assert "python_runtime.inspect_runtime" in starter
    assert 'set "MARVIN_PYTHON=%~dp0backend\\.venv\\Scripts\\python.exe"' in starter
    assert "Doctor verifiera l'allocation et la residence GPU" in starter
    assert "resolve-ollama-context-profile.ps1" in starter
    assert "resolve-ollama-context-profile.py" in context_resolver
    assert "le Cloud ne recoit aucun override de contexte" in starter
    assert "New-ScheduledTaskTrigger -AtLogOn" in autostart
    assert "-LogonType Interactive" in autostart
    assert "-RunLevel Limited" in autostart
    assert "-RemoteAddress LocalSubnet" in autostart
    assert "Marvin - Frontend" in autostart and "Remove-NetFirewallRule" in autostart
    assert "-LocalPort 3000" not in autostart
    assert "-LocalPort 8005" not in autostart
    print("Installation portable OK - socle, capacités optionnelles, rapport et avatar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
