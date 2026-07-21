"""Bind the validated Windows VM to Test Forge without exposing its password."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import hyperv_test_runner


def main() -> int:
    result = hyperv_test_runner.configure_from_stored_secret(
        vm_name="Marvin-Windows11-TestForge", checkpoint_name="Marvin-Clean",
        guest_username="marvin", confirmed=True,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
