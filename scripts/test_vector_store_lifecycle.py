"""Contrat de fermeture explicite et idempotente du client Qdrant local."""

from __future__ import annotations

import asyncio
import sys
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
    print("Qdrant lifecycle OK - fermeture explicite, unique et idempotente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
