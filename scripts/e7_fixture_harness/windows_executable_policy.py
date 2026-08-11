from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping


POWERSHELL = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def attest_winget(permission: Mapping[str, Any]) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("fixture_system_binary_unavailable:windows_required")
    if permission.get("identity") != "windows_signed_system_binary":
        raise RuntimeError("fixture_system_binary_denied:identity")
    script = (
        "$ErrorActionPreference='Stop';"
        "$p=Get-AppxPackage -Name Microsoft.DesktopAppInstaller|Sort-Object Version -Descending|Select-Object -First 1;"
        "if($null -eq $p){throw 'DesktopAppInstaller absent'};"
        "$f=Join-Path $p.InstallLocation 'winget.exe';"
        "$s=Get-AuthenticodeSignature -LiteralPath $f;"
        "[pscustomobject]@{path=$f;status=[string]$s.Status;subject=$s.SignerCertificate.Subject;"
        "thumbprint=$s.SignerCertificate.Thumbprint;package_version=[string]$p.Version}|ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("fixture_system_binary_attestation_failed")
    evidence = json.loads(completed.stdout)
    path = Path(evidence["path"]).resolve()
    expected_status = str(permission.get("authenticode_status", "Valid"))
    expected_publisher = str(permission.get("publisher", ""))
    if evidence.get("status") != expected_status:
        raise RuntimeError("fixture_system_binary_denied:authenticode_status")
    if expected_publisher and expected_publisher.casefold() not in str(evidence.get("subject", "")).casefold():
        raise RuntimeError("fixture_system_binary_denied:publisher")
    if not path.is_file():
        raise RuntimeError("fixture_system_binary_denied:path")
    return {
        "id": permission["id"],
        "path": str(path),
        "identity": permission["identity"],
        "authenticode_status": evidence["status"],
        "publisher_subject": evidence["subject"],
        "signer_thumbprint": evidence["thumbprint"],
        "package_version": evidence["package_version"],
        "allowed_argv": ((str(path), "--version"),),
        "allowed_environment": tuple(permission.get("allowed_environment", ())),
    }
