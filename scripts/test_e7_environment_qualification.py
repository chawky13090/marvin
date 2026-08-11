from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qualify_e7_pilot_environments import _memory_preflight


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-e7-qualification-test-") as temporary:
        output = Path(temporary) / "qualification.json"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "qualify_e7_pilot_environments.py"), "--output", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["status"] == "qualified_no_business_tool_execution"
        assert report["tool_execution_authorized"] is False
        assert report["host_execution_forbidden"] is True
        assert report["business_tools_invoked"] == []
        assert report["pilot_contract_count"] == 6
        assert report["pilot_implementation_count"] == 6
        assert report["local_isolation"]["qualified"] is True
        assert report["windows_vm_isolation"]["qualified"] is True
        assert report["windows_vm_isolation"]["configuration_qualified"] is True
        assert report["windows_vm_isolation"]["state"] == "Off"
        assert report["windows_vm_isolation"]["checkpoint_name"] == "Marvin-Clean"
        memory = report["windows_vm_isolation"]["campaign_memory_preflight"]
        assert memory["status"] in {"ready", "blocked_transient_host_memory"}
        assert memory["gate_blocking"] is False
        assert memory["must_be_rechecked_immediately_before_vm_start"] is True
        assert "qualification_does_not_set_E7" in report["limitations"]
        assert _memory_preflight({"host_free_memory_bytes": 3, "startup_bytes": 4})["status"] == "blocked_transient_host_memory"
        assert _memory_preflight({"host_free_memory_bytes": 4, "startup_bytes": 4})["status"] == "ready"
    print("E7 Environment Qualification OK - local isolation and locked Windows VM qualified without tool execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
