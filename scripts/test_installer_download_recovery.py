"""Exercise the real download helper against interrupted local HTTP responses.

No installer, external network, trust store or system configuration is modified.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = b"marvin-download-fixture\n" * 4096


def main() -> int:
    counts: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass  # Local synthetic payload only; no access log is needed.

        def do_GET(self) -> None:
            counts[self.path] = counts.get(self.path, 0) + 1
            body = b"corrupt" if self.path == "/corrupt" else PAYLOAD
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.path == "/interrupted" and counts[self.path] == 1:
                self.wfile.write(body[:100])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="marvin-download-test-") as directory:
            root = Path(directory)
            helper = ROOT / "scripts/install-marvin-oneclick.ps1"
            script = root / "check.ps1"
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            base = f"http://127.0.0.1:{server.server_port}"
            script.write_text(
                "$ErrorActionPreference='Stop'\nSet-StrictMode -Version Latest\n"
                "Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop\n"
                f"$Source={quote(helper)}\n$DownloadRoot={quote(root / 'downloads')}\n"
                "$DownloadedEvidence=[System.Collections.Generic.List[object]]::new()\n"
                "$Tokens=$null;$Errors=$null\n"
                "$Ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$Tokens,[ref]$Errors)\n"
                "if($Errors.Count){throw 'Source parse error'}\n"
                "$Function=$Ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-VerifiedDownload'},$true)\n"
                "if($null -eq $Function){throw 'Missing download helper'}\n"
                ". ([scriptblock]::Create($Function.Extent.Text))\n"
                f"$Expected={quote(hashlib.sha256(PAYLOAD).hexdigest())}\n"
                f"$Url={quote(base + '/interrupted')}\n"
                "$Path=Get-VerifiedDownload -Name 'fixture.bin' -Url $Url -Sha256 $Expected\n"
                "if((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected){throw 'Invalid accepted bytes'}\n"
                "$Again=Get-VerifiedDownload -Name 'fixture.bin' -Url $Url -Sha256 $Expected\n"
                "if($Again -ne $Path){throw 'Cache identity changed'}\n"
                "[IO.File]::WriteAllText($Path,'corrupt cached bytes')\n"
                "$Repaired=Get-VerifiedDownload -Name 'fixture.bin' -Url $Url -Sha256 $Expected\n"
                "if((Get-FileHash -LiteralPath $Repaired).Hash.ToLowerInvariant() -ne $Expected){throw 'Cache not repaired'}\n"
                "$Rejected=$false\ntry {\n"
                f"Get-VerifiedDownload -Name 'rejected.bin' -Url {quote(base + '/corrupt')} -Sha256 $Expected | Out-Null\n"
                "} catch { $Rejected=$true }\n"
                "if(-not $Rejected){throw 'Corrupt download accepted'}\n"
                "if(Test-Path (Join-Path $DownloadRoot 'rejected.bin')){throw 'Corrupt final cache retained'}\n"
                "if(@(Get-ChildItem $DownloadRoot -Filter '*.part').Count){throw 'Partial download retained'}\n"
                "if($DownloadedEvidence.Count -ne 3){throw 'Failed download recorded as evidence'}\n"
                "@{success=$true;evidence_count=$DownloadedEvidence.Count}|ConvertTo-Json -Compress\n",
                encoding="utf-8", newline="\n",
            )
            powershell = shutil.which("powershell.exe")
            assert powershell, "Windows PowerShell 5.1 required"
            result = subprocess.run(
                [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=60, check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert json.loads(result.stdout)["success"] is True
            assert counts == {"/interrupted": 3, "/corrupt": 3}, counts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print("Installer download recovery OK - interruption, cache, corruption, bounded retries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
