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
    assert "npm ci" in installer
    assert "nomic-embed-text" in installer
    assert "[1/9]" in installer
    assert "install-desktop-avatar.ps1" in installer
    assert "plan_local_models.py" in installer
    assert "qwen2.5:7b" not in installer
    assert "llava-phi3" not in installer
    assert "write-install-report.ps1" in installer
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
