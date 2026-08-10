"""Caracterise le retry borne du smoke HTTP en lecture seule."""

from __future__ import annotations

import io
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import smoke_test_api as smoke  # noqa: E402


class _Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class _Opener:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def open(self, _request: object, *, timeout: int) -> _Response:
        assert timeout == smoke.READ_TIMEOUT_SECONDS
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, bytes)
        return _Response(outcome)


def main() -> int:
    original = smoke.HTTP
    original_sleep = smoke.time.sleep
    try:
        opener = _Opener([socket.timeout("charge transitoire"), b'{"status":"ok"}'])
        smoke.HTTP = opener
        smoke.time.sleep = lambda _seconds: None
        assert smoke.fetch_json("http://marvin.test/api/health") == {"status": "ok"}
        assert opener.calls == 2

        opener = _Opener([socket.timeout("un"), socket.timeout("deux")])
        smoke.HTTP = opener
        try:
            smoke.fetch_json("http://marvin.test/api/health")
        except socket.timeout:
            pass
        else:
            raise AssertionError("Le second timeout doit rester bloquant.")
        assert opener.calls == 2

        opener = _Opener([ValueError("erreur non reseau")])
        smoke.HTTP = opener
        try:
            smoke.fetch_json("http://marvin.test/api/health")
        except ValueError:
            pass
        else:
            raise AssertionError("Une erreur non transitoire ne doit jamais etre rejouee.")
        assert opener.calls == 1
    finally:
        smoke.HTTP = original
        smoke.time.sleep = original_sleep

    print("Smoke API resilience OK - un retry GET borne, aucune mutation rejouee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
