"""Smoke test réel et volontairement connecté de Test Forge sous Debian 13."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import test_forge


def main() -> int:
    code = "def answer() -> int:\n    return 42\n"
    tests = (
        "import unittest\n"
        "import main\n\n"
        "class AnswerTests(unittest.TestCase):\n"
        "    def test_answer(self):\n"
        "        self.assertEqual(main.answer(), 42)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )
    integration = (
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        "apt-get update\n"
        "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3\n"
        "python3 -c \"import sys; assert sys.version_info >= (3, 11)\"\n"
        "echo MARVIN_INTEGRATION_COMPLETE=full\n"
    )
    result = test_forge.execute(
        code,
        "python",
        test_code=tests,
        integration_test_code=integration,
        require_online=True,
        timeout_seconds=180,
    )
    if not result.get("production_ready"):
        print(result)
        return 1
    online = next(
        step for step in result["steps"] if step["name"] == "online_integration"
    )
    assert online["completion_marker"] is True
    assert online["test_completion_marker"] is True
    print(
        "Test Forge Online OK - dépendances Debian téléchargées et unittest "
        "exécuté par le runner."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
