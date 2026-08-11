from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "benchmarks" / "runtime-readiness" / "cold-start-v2.620.json"
ERRATUM = ROOT / "benchmarks" / "runtime-readiness" / "cold-start-v2.620-erratum-v1.1.json"


def main() -> int:
    status = (ROOT / "scripts" / "get-marvin-runtime-status.ps1").read_text(encoding="utf-8-sig")
    restart = (ROOT / "scripts" / "restart-marvin.ps1").read_text(encoding="utf-8-sig")
    runner = (ROOT / "scripts" / "verify-marvin-cold-starts.ps1").read_text(encoding="utf-8-sig")
    assert "/api/coding/overview" in status and "/api/vm-lab/status" in status
    assert "$HeavyReady" in status and "'initializing'" in status
    assert "$StatusDeadline = $Deadline" in restart
    assert "$StableStatusChecks -ge 2" in restart
    assert "readiness = $Status.readiness" in restart
    assert "[ValidateRange(1, 10)][int]$Cycles = 5" in runner
    assert "$Status.state -ne 'ready'" in runner
    assert "startup_wait_ms = [int64]$Status.startup_wait_ms" in runner
    assert "cycle_total_ms" in runner
    assert "startup_wait_ms" in restart and "stop_duration_ms" in restart
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    erratum = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert erratum["source_report_sha256"] == hashlib.sha256(REPORT.read_bytes()).hexdigest()
    assert erratum["corrections"]["startup_wait_ms"] == "not_separately_recorded_in_v2.620"
    assert erratum["corrections"]["accepted_state"] == "ready_only"
    assert erratum["historical_report_modified"] is False
    assert report["passed"] is True
    assert len(report["cycles"]) == 5
    assert [item["cycle"] for item in report["cycles"]] == [1, 2, 3, 4, 5]
    assert all(item["state"] == "ready" for item in report["cycles"])
    assert all(item["code_workspace_http"] == 200 for item in report["cycles"])
    assert all(item["vm_lab_http"] == 200 for item in report["cycles"])
    assert report["acceptance"]["timeout_was_not_increased"] is True
    print("Startup Readiness OK - 5 cycles, Code Workspace et VM Lab prêts avant ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
