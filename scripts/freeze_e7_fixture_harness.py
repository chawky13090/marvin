from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "scripts" / "e7_fixture_harness"
OUTPUT = ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "pilot-fixture-harness-manifest.json"


def main() -> int:
    sources = sorted(PACKAGE.glob("*.py"))
    sources.extend(
        [
            ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "direct-fixture-contracts.json",
            ROOT / "benchmarks" / "tool-evidence" / "v1.1" / "direct-fixture-pilot.json",
        ]
    )
    value = {
        "schema": "marvin.pilot-fixture-harness-manifest/1.0",
        "status": "implementation_frozen_execution_locked",
        "fixture_plans": 6,
        "tool_execution_authorized": False,
        "host_execution_forbidden": True,
        "runtime_guard": {
            "process_isolation_required": True,
            "meta_path_allow_list": True,
            "stdlib_origin_validation": True,
            "dynamic_exec_compile_denied": True,
            "positive_canary_required": True,
            "negative_import_canary_required": True,
            "negative_dynamic_code_canary_required": True,
            "audit_hook_never_installed_in_backend": True,
        },
        "files": {},
        "rollback": "revert the atomic v2.616 commit; no fixture or Marvin tool was executed",
    }
    for path in sources:
        relative = path.relative_to(ROOT).as_posix()
        value["files"][relative] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
    OUTPUT.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
