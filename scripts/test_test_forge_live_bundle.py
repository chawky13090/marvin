"""Live Docker smoke test proving that Test Forge validates supporting source files."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import test_forge


def main() -> int:
    test_code = (
        "import unittest\n"
        "from src.service import double\n\n"
        "class ServiceTests(unittest.TestCase):\n"
        "    def test_double(self) -> None:\n"
        "        self.assertEqual(double(21), 42)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )
    valid = test_forge.execute(
        "from src.service import double\n\ndef main() -> int:\n    return double(21)\n",
        "python",
        test_code=test_code,
        files={"src/service.py": "def double(value: int) -> int:\n    return value * 2\n"},
    )
    if not valid.get("production_ready"):
        raise AssertionError(f"Le bundle valide a échoué : {valid}")

    invalid = test_forge.execute(
        "def main() -> int:\n    return 0\n",
        "python",
        test_code="import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n",
        files={"src/broken.py": "def broken(:\n    pass\n"},
    )
    failed = set(invalid.get("failed_steps") or [])
    if "python_compile" not in failed:
        raise AssertionError(f"Le module auxiliaire invalide n'a pas été détecté : {invalid}")

    print("Test Forge Bundle Live OK - sources auxiliaires exécutées et défaut récursif détecté.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
