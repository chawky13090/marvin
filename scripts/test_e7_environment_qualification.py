from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
        assert report["windows_vm_isolation"]["state"] == "Off"
        assert report["windows_vm_isolation"]["checkpoint_name"] == "Marvin-Clean"
        assert "qualification_does_not_set_E7" in report["limitations"]
    print("E7 Environment Qualification OK - local isolation and locked Windows VM qualified without tool execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
