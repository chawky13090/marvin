"""Deterministic Marvin Engineering Runtime regressions."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import engineering_runtime


def accepted_result() -> dict:
    return {
        "success": True,
        "files": {"main.py": "print('ok')\n"},
        "critical_issues": 0,
        "high_issues": 0,
        "test_report": {"tests_executed": True, "production_ready": True, "steps": []},
        "production_contract": {"success": True, "failures": []},
    }


def main() -> int:
    success = engineering_runtime.normalize_tool_result("file_read", {"success": True}, duration_ms=12)
    assert success["_contract"]["status"] == "succeeded"
    assert success["_contract"]["duration_ms"] == 12
    reversible = engineering_runtime.normalize_tool_result(
        "bulk_rename",
        {"success": True, "rollback_manifest": "manifest.json"},
    )
    assert reversible["_contract"]["rollback_available"] is True
    completed_rollback = engineering_runtime.normalize_tool_result(
        "bulk_rename",
        {
            "success": True,
            "rollback_manifest": "manifest.json",
            "rollback_available": False,
        },
    )
    assert completed_rollback["_contract"]["rollback_available"] is False

    failure = engineering_runtime.normalize_tool_result(
        "pc_run_command", {"success": False, "error": "code 1", "retryable": True},
    )
    assert failure["_contract"]["status"] == "failed"
    assert failure["_contract"]["retryable"] is True

    confirmation = engineering_runtime.normalize_tool_result(
        "file_delete", {"requiresConfirmation": True, "message": "Confirmer"},
    )
    assert confirmation["_contract"]["error_code"] == "CONFIRMATION_REQUIRED"

    classified = engineering_runtime.classify_failure({
        "success": False,
        "error": "unittest assertion failed",
        "test_report": {"failed_steps": ["unittest"]},
    })
    assert classified["category"] == "test_or_code" and classified["retryable"] is True
    assert len(classified["signature"]) == 64

    class FakeResponse:
        def __init__(self, status_code: int, text: str = ""):
            self.status_code = status_code
            self.text = text
            self.headers = {"content-type": "text/html", "content-length": str(len(text))}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def head(self, _url: str):
            return FakeResponse(404)
        def get(self, _url: str, headers=None):
            return FakeResponse(200, '<a href="artifact-2.deb">artifact-2.deb</a>')

    with (
        patch.object(engineering_runtime.socket, "getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ]),
        patch.object(engineering_runtime.httpx, "Client", FakeClient),
    ):
        urls = engineering_runtime.diagnose_public_urls({
            "main.sh": "wget https://downloads.example.com/releases/artifact-1.deb",
        })
    assert urls[0]["status"] == 404
    assert urls[0]["alternatives"] == [
        "https://downloads.example.com/releases/artifact-2.deb"
    ]

    result = accepted_result()
    linux_done = engineering_runtime.definition_of_done(result, targets={"linux"})
    assert linux_done["success"] is True
    linux_native_refused = engineering_runtime.definition_of_done(
        result,
        targets={"linux"},
        linux_validation={"production_ready": False},
    )
    assert linux_native_refused["success"] is False
    linux_native_done = engineering_runtime.definition_of_done(
        result,
        targets={"linux"},
        linux_validation={"production_ready": True},
    )
    assert linux_native_done["success"] is True
    windows_refused = engineering_runtime.definition_of_done(result, targets={"windows"})
    assert windows_refused["success"] is False
    assert "windows_native_execution" in windows_refused["failures"]
    windows_done = engineering_runtime.definition_of_done(
        result, targets={"windows"}, windows_validation={"native_execution_validated": True},
    )
    assert windows_done["success"] is True

    pack = engineering_runtime.delivery_pack(
        {"id": "a" * 32, "request": "Créer", "target_platforms": ["linux"]},
        {**result, "models_consulted": ["model"], "password": "do-not-leak"},
        linux_done,
    )
    assert pack["schema"] == "marvin.delivery-pack/1.0"
    assert pack["manifest"][0]["sha256"]
    assert "do-not-leak" not in str(pack)
    print("Engineering Runtime OK - contrats, classification, DoD et Delivery Pack.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
