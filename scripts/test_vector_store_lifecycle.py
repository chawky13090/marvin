"""Contrat de fermeture explicite et idempotente du client Qdrant local."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import vector_store


class FakeClient:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


async def main() -> int:
    previous_client = vector_store._client
    previous_migrated = vector_store._memory_payloads_migrated
    fake = FakeClient()
    try:
        vector_store._client = fake
        vector_store._memory_payloads_migrated = True
        await vector_store.close_runtime()
        await vector_store.close_runtime()
        assert fake.close_count == 1
        assert vector_store._client is None
        assert vector_store._memory_payloads_migrated is False
    finally:
        vector_store._client = previous_client
        vector_store._memory_payloads_migrated = previous_migrated
    with tempfile.TemporaryDirectory(prefix="marvin-qdrant-exit-") as directory:
        marker = Path(directory) / "closed.txt"
        code = (
            "from pathlib import Path; import vector_store; "
            "P=Path(r'" + str(marker) + "'); "
            "C=type('C',(),{'close':lambda self:P.write_text('closed',encoding='utf-8')}); "
            "vector_store._client=C()"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT / "backend",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert marker.read_text(encoding="utf-8") == "closed"
        assert "Exception ignored" not in completed.stderr
    print("Qdrant lifecycle OK - fermeture explicite, unique et idempotente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
