from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import server_runtime


class FakeServer:
    should_exit = False


async def test_backend_shutdown_request() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-lifecycle-") as directory:
        request = Path(directory) / "backend.shutdown"
        server = FakeServer()
        with patch.object(server_runtime, "SHUTDOWN_REQUEST", request):
            watcher = asyncio.create_task(server_runtime._watch_shutdown(server))
            await asyncio.sleep(0.02)
            assert not server.should_exit
            request.write_text("test", encoding="utf-8")
            await asyncio.wait_for(watcher, timeout=1.0)
            assert server.should_exit


def test_contract_files() -> None:
    stop = (ROOT / "scripts" / "stop-marvin.ps1").read_text(encoding="utf-8-sig")
    frontend = (ROOT / "scripts" / "start_next_dev.mjs").read_text(encoding="utf-8")
    starter = (ROOT / "start.bat").read_text(encoding="utf-8-sig")
    backend_starter = (ROOT / "backend" / "start.bat").read_text(encoding="utf-8-sig")
    backend_runtime = (ROOT / "backend" / "server_runtime.py").read_text(encoding="utf-8-sig")
    production = (ROOT / "START-PRODUCTION.bat").read_text(encoding="utf-8-sig")
    restart = (ROOT / "scripts" / "restart-marvin.ps1").read_text(encoding="utf-8-sig")
    assert "New-ShutdownRequest -Name 'backend.shutdown'" in stop
    assert "New-ShutdownRequest -Name 'frontend.shutdown'" in stop
    assert "Get-MarvinListeners" in stop
    assert "NoForceFallback" in stop
    assert "lifecycle.jsonl" in stop
    assert "preserved_ollama = $true" in stop
    assert "caddy.exe" in stop and "Start-Process -FilePath $Caddy" in stop
    assert "$CaddyStop.ExitCode" in stop
    assert "frontend.shutdown" in frontend
    assert "child.kill('SIGTERM')" in frontend
    assert "stopping ? 0" in frontend
    assert "POST_SHUTDOWN_DRAIN_SECONDS" in backend_runtime
    assert "threading.Timer" in backend_runtime
    assert "timeout_graceful_shutdown=10" in backend_runtime
    assert "marvin-startup-lock.ps1" in starter
    assert "stop-requested" in starter
    assert "call npm run dev" in starter
    assert not starter.rstrip().endswith("pause")
    assert not backend_starter.rstrip().endswith("pause")
    assert "call \"%~dp0start.bat\"" in production
    assert "npm run start" not in production
    assert "Get-MarvinRuntimeProcesses" in stop
    assert "signal-stop" in stop
    assert "stop-marvin.ps1" in restart
    assert "get-marvin-runtime-status.ps1" in restart
    assert "startup_timeout_or_exit" in restart
    assert "dependencies = $Status.dependencies" in restart
    assert "$FinalSuccess" in restart
    assert "if (-not $FinalSuccess) { exit 1 }" in restart


if __name__ == "__main__":
    asyncio.run(test_backend_shutdown_request())
    test_contract_files()
    print("Lifecycle Runtime OK - arrêt coopératif, repli borné et journalisation.")
