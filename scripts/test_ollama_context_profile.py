"""Contrat du profil matériel appliqué par start.bat."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
import auto_config
import ollama_context_policy


SCRIPT = ROOT / "scripts" / "resolve-ollama-context-profile.py"
SPEC = importlib.util.spec_from_file_location("resolve_context_profile", SCRIPT)
assert SPEC and SPEC.loader
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)

CALIBRATOR_SCRIPT = ROOT / "scripts" / "calibrate-ollama-context.py"
CALIBRATOR_SPEC = importlib.util.spec_from_file_location("calibrate_context_profile", CALIBRATOR_SCRIPT)
assert CALIBRATOR_SPEC and CALIBRATOR_SPEC.loader
calibrator = importlib.util.module_from_spec(CALIBRATOR_SPEC)
CALIBRATOR_SPEC.loader.exec_module(calibrator)


def main() -> int:
    calibration_source = (ROOT / "scripts" / "calibrate-ollama-context.py").read_text(encoding="utf-8")
    assert '"taskkill.exe", "/PID", str(process.pid), "/T", "/F"' in calibration_source
    assert "ollama-context-profile.last-failed.json" in calibration_source
    assert '"excluded_from_quality_oracle": True' in calibration_source
    assert calibrator._extract_final_answer(
        "raisonnement qui cite CALIBRATION_OK sans répondre"
    ) != "CALIBRATION_OK"
    assert calibrator._extract_final_answer(
        "raisonnement\n</think>\nCALIBRATION_OK"
    ) == "CALIBRATION_OK"
    candidates = [
        {"context_tokens": 8192, "gpu_residency_ratio": 0.76, "kv_cache_type": "q8_0"},
        {"context_tokens": 32768, "gpu_residency_ratio": 0.59, "kv_cache_type": "q8_0"},
    ]
    gpu = {"vendor": "nvidia", "vram_gb": 4.0}
    assert calibrator._select_candidate(
        candidates, objective_tokens=32768, explicit_minimum=False, hardware=gpu,
    )["context_tokens"] == 8192
    assert calibrator._select_candidate(
        candidates, objective_tokens=32768, explicit_minimum=True, hardware=gpu,
    )["context_tokens"] == 32768
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "profile.json"
        assert resolver.resolve(path)["status"] == "bootstrap_unverified"
        machine = resolver._fingerprint(auto_config.detect_hardware())
        path.write_text(
            json.dumps(
                {
                    "schema": "marvin.ollama-context-profile/1.1",
                    "status": "verified",
                    "machine_key": ollama_context_policy.machine_profile_key(machine),
                    "model": "qwen:4b",
                    "model_digest": "abc",
                    "selected": {"context_tokens": 32768, "kv_cache_type": "q8_0"},
                }
            ),
            encoding="utf-8",
        )
        result = resolver.resolve(path)
        assert result["status"] == "verified"
        assert result["context_tokens"] == 32768
        assert result["kv_cache_type"] == "q8_0"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema"] = "marvin.ollama-context-profile/1.0"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert resolver.resolve(path)["status"] == "bootstrap_unverified"
        payload["schema"] = "marvin.ollama-context-profile/1.1"
        payload["machine_key"] = "other-machine"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert resolver.resolve(path)["status"] == "bootstrap_unverified"
    print("Ollama context profile OK - profil lié à la machine et repli borné.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
