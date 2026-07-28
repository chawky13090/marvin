"""Contrat des erreurs internes API : aucune fuite et corrélation stable."""
from __future__ import annotations

import sys
import re
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api_errors
import api_observability


def main() -> int:
    secret = RuntimeError(r"password=hunter2 C:\Users\private\secret.txt")
    token = api_observability._current_request_id.set("request-test-1234")
    try:
        with patch.object(api_errors.bug_log, "log_bug") as logged:
            error = api_errors.internal_http_error(
                "email_read",
                secret,
                "Lecture du message impossible.",
            )
            payload = api_errors.safe_failure(
                "email_list",
                secret,
                "Lecture de la boîte impossible.",
                emails=[],
            )
    finally:
        api_observability._current_request_id.reset(token)

    assert error.status_code == 500
    assert error.headers["X-Request-ID"] == "request-test-1234"
    assert len(error.headers["X-Incident-ID"]) == 32
    assert "hunter2" not in str(error.detail)
    assert "secret.txt" not in str(error.detail)
    assert payload["emails"] == []
    assert payload["request_id"] == "request-test-1234"
    assert "hunter2" not in payload["error"]
    assert logged.call_count == 2
    for call in logged.call_args_list:
        assert "hunter2" not in str(call)
        assert "secret.txt" not in str(call)
    api_sources = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in sorted((ROOT / "backend" / "api").glob("*.py"))
    )
    forbidden = (
        r"status_code\s*=\s*500[^\n]*detail\s*=\s*str\(",
        r"status_code\s*=\s*500[^\n]*detail\s*=\s*f[\"'][^\"']*\{(?:exc|error)",
        r"[\"']error[\"']\s*:\s*str\((?:exc|error)\)",
    )
    for pattern in forbidden:
        assert not re.search(pattern, api_sources), f"Fuite d'exception API détectée : {pattern}"
    print("API Errors OK - incidents corrélés, réponses stables et exceptions expurgées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
