"""Live smoke test for the configured Windows Hyper-V Test Forge runner."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import hyperv_test_runner  # noqa: E402


files = {
    "test_smoke.py": """import unittest


class WindowsRunnerSmokeTest(unittest.TestCase):
    def test_runtime_and_filesystem(self):
        self.assertEqual((21 * 2), 42)


if __name__ == \"__main__\":
    unittest.main()
""",
}

status = hyperv_test_runner.status()
if not status.get("ready"):
    raise SystemExit("Runner Hyper-V indisponible: " + str(status.get("error")))

result = hyperv_test_runner.execute(
    files,
    hyperv_test_runner.commands_for("python", files),
    confirmed=True,
    timeout_seconds=900,
)
print(json.dumps(result, ensure_ascii=False, indent=2))
if not result.get("production_ready"):
    raise SystemExit("Le smoke test Windows natif n est pas production_ready.")
