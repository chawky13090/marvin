"""Capability matrix must never overclaim an untested language."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import deliverable_bundle
import language_registry
import test_forge


def main() -> int:
    assert language_registry.normalize("golang") == "go"
    assert language_registry.is_certified("go", "linux") is True
    assert language_registry.is_certified("go", "windows") is False
    assert language_registry.can_cross_compile("go", "windows") is True
    assert language_registry.is_certified("powershell", "linux") is False
    assert language_registry.is_certified("rust") is False
    certified = [item for item in language_registry.matrix() if item["level"] == "certified"]
    for item in certified:
        language = item["language"]
        assert language in deliverable_bundle.PRIMARY_NAMES
        assert language == "powershell" or language in test_forge.FILE_NAMES
        assert item["checks"]
    print("Language Matrix OK - capacités certifiées séparées des toolchains planifiées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
