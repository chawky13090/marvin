"""Real pip, loopback-only broken transfer, and a persistent reboot witness.

This certifies pip recovery in a confined target, not the complete installer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NAME = "marvin_recovery_fixture-1.0-py3-none-any.whl"
MODULE = b"VALUE = 'marvin-recovery-witness-v1'\n"


def verify(root: Path) -> dict:
    receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
    module = root / "target/marvin_recovery_fixture/__init__.py"
    assert hashlib.sha256(module.read_bytes()).hexdigest() == receipt["module_sha256"]
    assert receipt["interrupted_exit_code"] != 0
    assert receipt["retry_exit_code"] == 0
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = args.work_dir.resolve()
    if args.verify_only:
        verify(root)
        print(json.dumps({"post_reboot_witness_verified": True}))
        return 0
    root.mkdir(parents=True, exist_ok=False)
    wheel = root / NAME
    prefix = "marvin_recovery_fixture-1.0.dist-info/"
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("marvin_recovery_fixture/__init__.py", MODULE)
        archive.writestr("marvin_recovery_fixture/padding.bin", b"x" * (4 * 1024 * 1024))
        archive.writestr(prefix + "METADATA", "Metadata-Version: 2.1\nName: marvin-recovery-fixture\nVersion: 1.0\n")
        archive.writestr(prefix + "WHEEL", "Wheel-Version: 1.0\nGenerator: marvin-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(prefix + "RECORD", "")
    payload = wheel.read_bytes()
    state = {"interrupt": True, "broken_requests": 0, "healthy_requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass  # Synthetic local fixture; no access log or user data.

        def do_GET(self) -> None:
            if self.path != "/" + NAME:
                self.send_error(404)
                return
            key = "broken_requests" if state["interrupt"] else "healthy_requests"
            state[key] += 1
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if state["interrupt"]:
                self.wfile.write(payload[:1024])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
            else:
                self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        command = [sys.executable, "-m", "pip", "install", "--isolated",
                   "--disable-pip-version-check", "--no-cache-dir", "--no-deps",
                   "--no-index", "--retries", "0", "--timeout", "5",
                   "--target", str(root / "target"),
                   f"http://127.0.0.1:{server.server_port}/{NAME}"]
        broken = subprocess.run(command, capture_output=True, timeout=90, check=False)
        (root / "interrupted.log").write_bytes(broken.stdout + broken.stderr)
        assert broken.returncode != 0, "Interrupted transfer reported success"
        assert not (root / "target/marvin_recovery_fixture/__init__.py").exists()
        assert state["broken_requests"] > 0
        state["interrupt"] = False
        healthy = subprocess.run(command, capture_output=True, timeout=90, check=False)
        (root / "retry.log").write_bytes(healthy.stdout + healthy.stderr)
        assert healthy.returncode == 0, healthy.stderr.decode(errors="replace")
        assert state["healthy_requests"] > 0
        module = root / "target/marvin_recovery_fixture/__init__.py"
        assert module.read_bytes() == MODULE
        receipt = {
            "schema": "marvin.pip-network-recovery/1",
            "python_version": sys.version.split()[0],
            "interrupted_exit_code": broken.returncode,
            "retry_exit_code": healthy.returncode,
            "broken_requests": state["broken_requests"],
            "healthy_requests": state["healthy_requests"],
            "module_sha256": hashlib.sha256(MODULE).hexdigest(),
            "wheel_sha256": hashlib.sha256(payload).hexdigest(),
            "real_pip": True, "loopback_only": True,
            "full_installer_resume_certified": False,
        }
        (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
        verify(root)
        print(json.dumps(receipt))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
