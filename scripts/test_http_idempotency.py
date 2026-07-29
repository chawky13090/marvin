"""Régressions de l'adaptateur d'idempotence des mutations HTTP critiques."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import action_replay
import api_observability
import http_idempotency
from db_connection import db
from db_migrations import MIGRATIONS, apply_migrations


async def _exercise(path: Path) -> None:
    calls = 0

    async def mutate():
        nonlocal calls
        calls += 1
        return {"success": True, "resource_id": "stable"}

    key = uuid.uuid4()
    with patch.object(action_replay, "db", lambda: db(path)):
        without_key = await http_idempotency.execute(
            operation_name="http_test_create",
            payload={"value": 1},
            operation=mutate,
            idempotency_key=None,
            success_status=201,
        )
        assert without_key == {"success": True, "resource_id": "stable"}

        first = await http_idempotency.execute(
            operation_name="http_test_create",
            payload={"value": 1, "password": "never-persist-this"},
            operation=mutate,
            idempotency_key=key,
            success_status=201,
        )
        second = await http_idempotency.execute(
            operation_name="http_test_create",
            payload={"value": 1, "password": "never-persist-this"},
            operation=mutate,
            idempotency_key=key,
            success_status=201,
        )
        assert calls == 2
        assert first.status_code == second.status_code == 201
        assert first.headers["idempotency-replayed"] == "false"
        assert second.headers["idempotency-replayed"] == "true"
        assert json.loads(second.body) == {"success": True, "resource_id": "stable"}

        try:
            await http_idempotency.execute(
                operation_name="http_test_create",
                payload={"value": 2},
                operation=mutate,
                idempotency_key=key,
            )
        except http_idempotency.HTTPException as exc:
            assert exc.status_code == 422
            assert str(key) not in str(exc.detail)
        else:
            raise AssertionError("Une clé réutilisée avec un autre payload doit être refusée.")

        async def uncertain():
            raise ConnectionError("résultat externe inconnu")

        uncertain_key = uuid.uuid4()
        try:
            await http_idempotency.execute(
                operation_name="http_external_send",
                payload={"value": 3},
                operation=uncertain,
                idempotency_key=uncertain_key,
            )
        except ConnectionError:
            pass
        else:
            raise AssertionError("L'erreur métier initiale doit rester visible au handler.")
        try:
            await http_idempotency.execute(
                operation_name="http_external_send",
                payload={"value": 3},
                operation=mutate,
                idempotency_key=uncertain_key,
            )
        except http_idempotency.HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Un résultat externe inconnu ne doit pas être rejoué.")

    raw = path.read_bytes()
    assert str(key).encode("ascii") not in raw
    assert b"never-persist-this" not in raw


def main() -> int:
    api_observability.reset_for_tests()
    with tempfile.TemporaryDirectory(prefix="marvin-http-idempotency-") as directory:
        path = Path(directory) / "receipts.db"
        with db(path) as connection:
            apply_migrations(connection, MIGRATIONS)
        asyncio.run(_exercise(path))
        with db(path) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    frontend = (ROOT / "lib" / "backend.js").read_text(encoding="utf-8-sig")
    for route in (
        "/api/tools",
        "/api/mcp/execute",
        "/api/email/send",
        "/api/events",
        "/api/backups/restore",
        "/api/vm-lab/install",
        "/api/coding/projects",
    ):
        assert route in frontend
    assert r"/^\/api\/workflows\/[^/]+\/run$/" in frontend
    assert "crypto.randomUUID()" in frontend
    print("HTTP Idempotency OK - replay, fingerprint, incertitude et non-divulgation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
