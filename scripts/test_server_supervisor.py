"""Tests déterministes du superviseur Uvicorn Windows."""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import server_supervisor


class FakeProcess:
    def __init__(self, polls):
        self.polls = iter(polls)
        self.current = None

    def poll(self):
        try:
            self.current = next(self.polls)
        except StopIteration:
            pass
        return self.current


def clock():
    value = 0.0

    def now():
        nonlocal value
        value += 5.0
        return value

    return now


def main() -> int:
    response = patch("server_supervisor.urllib.request.urlopen")
    with response as mocked:
        mocked.return_value.__enter__.return_value.status = 200
        assert server_supervisor.probe_health() == "healthy"

    with patch("server_supervisor.urllib.request.urlopen", side_effect=socket.timeout):
        assert server_supervisor.probe_health() == "busy"

    with patch(
        "server_supervisor.urllib.request.urlopen",
        side_effect=server_supervisor.urllib.error.URLError(ConnectionRefusedError()),
    ):
        assert server_supervisor.probe_health() == "unreachable"

    healthy = iter([True, True, False, False, False])
    reason = server_supervisor.monitor_process(
        FakeProcess([None] * 8),
        probe=lambda: next(healthy),
        sleep=lambda _seconds: None,
        monotonic=clock(),
        failure_limit=3,
    )
    assert reason == "unhealthy"

    busy_then_healthy = iter(["healthy", "busy", "busy", "healthy", "unreachable"])
    reason = server_supervisor.monitor_process(
        FakeProcess([None, None, None, None, None, 0]),
        probe=lambda: next(busy_then_healthy),
        sleep=lambda _seconds: None,
        monotonic=clock(),
        failure_limit=2,
        busy_failure_limit=3,
    )
    assert reason == "exited"

    reason = server_supervisor.monitor_process(
        FakeProcess([None] * 8),
        probe=lambda: False,
        sleep=lambda _seconds: None,
        monotonic=clock(),
        startup_timeout=10,
    )
    assert reason == "startup_timeout"

    reason = server_supervisor.monitor_process(
        FakeProcess([7]),
        probe=lambda: True,
        sleep=lambda _seconds: None,
        monotonic=clock(),
    )
    assert reason == "exited"
    assert 3 <= server_supervisor.FAILURE_LIMIT <= 5
    assert server_supervisor.MAX_RESTARTS_PER_WINDOW <= 5
    print("Server Supervisor OK - santé, perte listener, démarrage et budget de relance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
