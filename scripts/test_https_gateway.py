"""Contrats statiques et smoke optionnel de la passerelle HTTPS Marvin."""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    template = (ROOT / "config" / "Caddyfile.marvin").read_text(encoding="utf-8")
    frontend = (ROOT / "lib" / "backend.js").read_text(encoding="utf-8")
    installer = (ROOT / "scripts" / "install-marvin-https.ps1").read_text(
        encoding="utf-8"
    )
    next_runtime = (ROOT / "scripts" / "start_next_dev.mjs").read_text(
        encoding="utf-8"
    )
    backend_runtime = (ROOT / "backend" / "server_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "tls internal" in template
    assert "uri strip_prefix /marvin-api" in template
    assert "reverse_proxy 127.0.0.1:8005" in template
    assert "reverse_proxy 127.0.0.1:3000" in template
    assert "tls_insecure_skip_verify" not in template
    assert "log {" not in template, "Les requêtes sensibles ne doivent pas être journalisées."
    assert "window.location.origin}/marvin-api" in frontend
    assert "2.11.4" in installer
    assert "ExpectedSha512" in installer
    assert "'127.0.0.1'" in next_runtime
    assert "'0.0.0.0'" not in next_runtime
    assert 'host="127.0.0.1"' in backend_runtime
    assert 'host="0.0.0.0"' not in backend_runtime

    state_path = ROOT / "runtime" / "https" / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["enabled"] is True
        assert state["port"] in range(1024, 65536)
        assert all(item.startswith("https://") for item in state["origins"])

    if os.getenv("MARVIN_HTTPS_LIVE") == "1":
        context = ssl.create_default_context()
        request = urllib.request.Request(
            "https://127.0.0.1:8443/marvin-api/api/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            assert response.status == 200
            assert json.load(response)["status"] == "ok"
            assert response.headers["Strict-Transport-Security"] == "max-age=86400"

    print("HTTPS Gateway OK - routage, intégrité, absence de logs sensibles et smoke.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
