"""Supervise Uvicorn sur Windows et répare une perte silencieuse du listener."""
from __future__ import annotations

import collections
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path


HEALTH_URL = "http://127.0.0.1:8005/api/health"
STARTUP_TIMEOUT_SECONDS = 120.0
PROBE_INTERVAL_SECONDS = 2.0
FAILURE_LIMIT = 5
BUSY_FAILURE_LIMIT = 30
RESTART_WINDOW_SECONDS = 600.0
MAX_RESTARTS_PER_WINDOW = 5


def probe_health(url: str = HEALTH_URL, timeout: float = 2.0) -> str:
    """Retourne healthy, busy ou unreachable sans ouvrir un socket orphelin."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return "healthy" if response.status == 200 else "busy"
    except urllib.error.HTTPError:
        return "busy"
    except (TimeoutError, socket.timeout):
        return "busy"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return "busy"
        return "unreachable"
    except OSError:
        return "unreachable"


def monitor_process(
    process,
    *,
    probe: Callable[[], str | bool] = probe_health,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    interval: float = PROBE_INTERVAL_SECONDS,
    failure_limit: int = FAILURE_LIMIT,
    busy_failure_limit: int = BUSY_FAILURE_LIMIT,
) -> str:
    """Retourne exited, startup_timeout ou unhealthy sans relancer lui-même."""
    started = monotonic()
    was_healthy = False
    failures = 0
    busy_failures = 0
    while process.poll() is None:
        sleep(interval)
        probe_result = probe()
        if probe_result is True or probe_result == "healthy":
            was_healthy = True
            failures = 0
            busy_failures = 0
            continue
        if not was_healthy:
            if monotonic() - started >= startup_timeout:
                return "startup_timeout"
            continue
        if probe_result == "busy":
            failures = 0
            busy_failures += 1
            if busy_failures >= busy_failure_limit:
                return "unhealthy"
            continue
        busy_failures = 0
        failures += 1
        if failures >= failure_limit:
            return "unhealthy"
    return "exited"


def stop_child(process) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    backend = Path(__file__).resolve().parent
    command = [
        sys.executable,
        str(backend / "server_runtime.py"),
    ]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    restarts: collections.deque[float] = collections.deque()

    try:
        while True:
            child = subprocess.Popen(
                command,
                cwd=backend,
                creationflags=creationflags,
            )
            reason = monitor_process(child)
            if reason == "exited" and int(child.returncode or 0) == 0:
                return 0
            if reason == "exited":
                reason = f"exited_{int(child.returncode or 1)}"

            print(
                f"[Marvin] Backend non sain ({reason}); relance contrôlée.",
                file=sys.stderr,
                flush=True,
            )
            stop_child(child)
            now = time.monotonic()
            while restarts and now - restarts[0] > RESTART_WINDOW_SECONDS:
                restarts.popleft()
            restarts.append(now)
            if len(restarts) > MAX_RESTARTS_PER_WINDOW:
                print(
                    "[Marvin] Trop de relances backend en dix minutes; arrêt du superviseur.",
                    file=sys.stderr,
                    flush=True,
                )
                return 1
            time.sleep(min(2 ** (len(restarts) - 1), 15))
    except KeyboardInterrupt:
        if child is not None:
            stop_child(child)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
