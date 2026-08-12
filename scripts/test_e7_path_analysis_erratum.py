from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.4"


def main() -> int:
    original = BASE / "path-analysis-preregistration.json"
    erratum = json.loads((BASE / "path-analysis-preregistration-erratum-v1.1.json").read_text(encoding="utf-8"))
    source = (ROOT / erratum["supplemental_source"]).read_text(encoding="utf-8")
    assert hashlib.sha256(original.read_bytes()).hexdigest() == erratum["original_policy_sha256"]
    assert "psutil.pid_exists" in source
    assert "psutil.Process(pid).create_time" in source
    assert "psutil.Process(pid).terminate" in source
    for forbidden in ("note_delete", "bulk_rename", "vm_lab_install", "code_workspace"):
        assert forbidden not in source.casefold()
    print("E7 Path Analysis Erratum OK - psutil observation/mutation canary frozen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
