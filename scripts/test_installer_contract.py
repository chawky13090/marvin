"""Contrat statique de l'installation Windows portable, sans mutation système."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    installer = (ROOT / "INSTALLER-NOUVEAU-PC.bat").read_text(encoding="utf-8")
    verifier = (ROOT / "VERIFIER-INSTALLATION.bat").read_text(encoding="utf-8")
    report = (ROOT / "scripts" / "write-install-report.ps1").read_text(encoding="utf-8")
    assert "npm ci" in installer
    assert "nomic-embed-text" in installer
    assert "[1/9]" in installer
    assert "install-desktop-avatar.ps1" in installer
    assert "write-install-report.ps1" in installer
    assert "Docker introuvable - Test Forge production indisponible" not in verifier
    assert "write-install-report.ps1" in verifier
    assert "install-capabilities.json" in report
    assert "Microsoft-Hyper-V-All" in report
    assert "Containers-DisposableClientVM" in report
    assert "Marvin-Debian13-TestForge" in report
    assert "Marvin-Windows11-TestForge" in report
    assert "overall = if ($CoreReady)" in report
    print("Installation portable OK - socle, capacités optionnelles, rapport et avatar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
