"""Contrat de minimisation et de reproductibilite de la telemetrie locale."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app_version import APP_VERSION
from execution_telemetry import DEFAULT_SELECTOR_VERSION, build_routing_context


def _spec(name: str, description: str) -> dict:
    return {
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        }
    }


def main() -> int:
    secret = "client-confidentiel-A17"
    settings = {
        "auto_config": {"mode": "eco"},
        "local_execution_telemetry": True,
    }
    first = build_routing_context(
        [_spec("file_find", secret), _spec("calculator", "calcul")],
        model_name="model:test",
        profile_name="agent",
        get_setting=settings.get,
    )
    reordered = build_routing_context(
        [_spec("calculator", "autre texte"), _spec("file_find", "autre")],
        model_name="model:test",
        profile_name="agent",
        get_setting=settings.get,
    )
    assert first == reordered
    assert first["app_version"] == APP_VERSION
    assert first["selector_version"] == DEFAULT_SELECTOR_VERSION
    assert first["candidate_count"] == 2
    assert len(first["candidate_set_sha256"]) == 64
    assert secret not in str(first)
    assert "file_find" not in str(first)

    disabled = build_routing_context(
        [_spec("file_find", secret)],
        model_name="model:test",
        profile_name="agent",
        get_setting={"local_execution_telemetry": False}.get,
    )
    assert disabled == {"app_version": APP_VERSION}
    print("Execution Telemetry OK - locale, minimale, stable et desactivable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
