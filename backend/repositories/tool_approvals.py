"""Demandes d'approbation persistantes liées à un appel d'outil exact."""

from __future__ import annotations

import json
import time
import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
FINAL_STATUSES = frozenset({"approved", "denied", "expired", "failed"})


class ToolApprovalRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS tool_approval_requests (
                id TEXT PRIMARY KEY,
                call_digest TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                conversation_id TEXT DEFAULT '',
                request_id TEXT DEFAULT '',
                source TEXT NOT NULL,
                risk_tier INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN (
                        'pending','executing','approved','denied','expired','failed'
                    )),
                expires_at REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                decided_at TEXT,
                decision_reason TEXT DEFAULT ''
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_tool_approvals_pending
               ON tool_approval_requests(status, expires_at)"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_tool_approvals_digest
               ON tool_approval_requests(call_digest, created_at DESC)"""
        )

    @staticmethod
    def _decode(row) -> dict | None:
        value = row_to_dict(row)
        if value is None:
            return None
        value["arguments"] = json.loads(value.pop("arguments_json"))
        return value

    def create_or_reuse(
        self,
        *,
        call_digest: str,
        tool_name: str,
        arguments: dict[str, Any],
        conversation_id: str,
        request_id: str,
        source: str,
        risk_tier: int,
        ttl_seconds: int = 300,
    ) -> dict:
        now = time.time()
        expires_at = now + min(max(int(ttl_seconds), 30), 900)
        payload = json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE tool_approval_requests
                   SET status = 'expired', decided_at = datetime('now'),
                       decision_reason = 'expired', arguments_json = '{}'
                   WHERE status = 'pending' AND expires_at <= ?""",
                (now,),
            )
            if conversation_id:
                connection.execute(
                    """UPDATE tool_approval_requests
                       SET status = 'expired', decided_at = datetime('now'),
                           decision_reason = 'superseded', arguments_json = '{}'
                       WHERE conversation_id = ? AND status = 'pending'
                         AND call_digest <> ?""",
                    (conversation_id, call_digest),
                )
            row = connection.execute(
                """SELECT * FROM tool_approval_requests
                   WHERE call_digest = ? AND status = 'pending'
                     AND expires_at > ?
                   ORDER BY created_at DESC LIMIT 1""",
                (call_digest, now),
            ).fetchone()
            if row is None:
                approval_id = str(uuid.uuid4())
                connection.execute(
                    """INSERT INTO tool_approval_requests (
                           id, call_digest, tool_name, arguments_json,
                           conversation_id, request_id, source, risk_tier,
                           expires_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        approval_id,
                        call_digest,
                        tool_name,
                        payload,
                        conversation_id,
                        request_id,
                        source,
                        int(risk_tier),
                        expires_at,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM tool_approval_requests WHERE id = ?",
                    (approval_id,),
                ).fetchone()
        result = self._decode(row)
        if result is None:
            raise RuntimeError("La demande d'approbation n'a pas été persistée.")
        return result

    def get(self, approval_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM tool_approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return self._decode(row)

    def resolve_status(self, approval_id: str) -> dict | None:
        """Retourne l'état autoritaire en expirant atomiquement une demande échue."""
        now = time.time()
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE tool_approval_requests
                   SET status = 'expired', decided_at = datetime('now'),
                       decision_reason = 'superseded', arguments_json = '{}'
                   WHERE id = ? AND status = 'pending'
                     AND conversation_id <> ''
                     AND EXISTS (
                         SELECT 1 FROM tool_approval_requests newer
                         WHERE newer.conversation_id =
                               tool_approval_requests.conversation_id
                           AND newer.rowid > tool_approval_requests.rowid
                     )""",
                (approval_id,),
            )
            connection.execute(
                """UPDATE tool_approval_requests
                   SET status = 'expired', decided_at = datetime('now'),
                       decision_reason = 'expired', arguments_json = '{}'
                   WHERE id = ? AND status = 'pending' AND expires_at <= ?""",
                (approval_id, now),
            )
            row = connection.execute(
                "SELECT * FROM tool_approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return self._decode(row)

    def claim(self, approval_id: str) -> dict | None:
        now = time.time()
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE tool_approval_requests
                   SET status = 'expired', decided_at = datetime('now'),
                       decision_reason = 'superseded', arguments_json = '{}'
                   WHERE id = ? AND status = 'pending'
                     AND conversation_id <> ''
                     AND EXISTS (
                         SELECT 1 FROM tool_approval_requests newer
                         WHERE newer.conversation_id =
                               tool_approval_requests.conversation_id
                           AND newer.rowid > tool_approval_requests.rowid
                     )""",
                (approval_id,),
            )
            row = connection.execute(
                "SELECT * FROM tool_approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return None
            if row["status"] == "pending" and float(row["expires_at"]) <= now:
                connection.execute(
                    """UPDATE tool_approval_requests
                       SET status = 'expired', decided_at = datetime('now'),
                           decision_reason = 'expired', arguments_json = '{}'
                       WHERE id = ? AND status = 'pending'""",
                    (approval_id,),
                )
                row = connection.execute(
                    "SELECT * FROM tool_approval_requests WHERE id = ?",
                    (approval_id,),
                ).fetchone()
                result = self._decode(row)
                if result is not None:
                    result["claimed"] = False
                return result
            if row["status"] != "pending":
                result = self._decode(row)
                if result is not None:
                    result["claimed"] = False
                return result
            updated = connection.execute(
                """UPDATE tool_approval_requests
                   SET status = 'executing', decision_reason = 'trusted_ui'
                   WHERE id = ? AND status = 'pending' AND expires_at > ?""",
                (approval_id, now),
            ).rowcount
            if updated != 1:
                result = self._decode(
                    connection.execute(
                        "SELECT * FROM tool_approval_requests WHERE id = ?",
                        (approval_id,),
                    ).fetchone()
                )
                if result is not None:
                    result["claimed"] = False
                return result
            row = connection.execute(
                "SELECT * FROM tool_approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        result = self._decode(row)
        if result is not None:
            result["claimed"] = True
        return result

    def finish(self, approval_id: str, *, approved: bool, reason: str = "") -> dict | None:
        status = "approved" if approved else "failed"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE tool_approval_requests
                   SET status = ?, decided_at = datetime('now'),
                       decision_reason = ?, arguments_json = '{}'
                   WHERE id = ? AND status = 'executing'""",
                (status, str(reason)[:500], approval_id),
            )
            row = connection.execute(
                "SELECT * FROM tool_approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return self._decode(row)

    def deny(self, approval_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE tool_approval_requests
                   SET status = 'denied', decided_at = datetime('now'),
                       decision_reason = 'user_denied', arguments_json = '{}'
                   WHERE id = ? AND status = 'pending'""",
                (approval_id,),
            )
            connection.execute(
                """UPDATE tool_approval_requests
                   SET status = 'expired', decided_at = datetime('now'),
                       decision_reason = 'superseded', arguments_json = '{}'
                   WHERE status = 'pending'
                     AND conversation_id = (
                         SELECT conversation_id FROM tool_approval_requests
                         WHERE id = ?
                     )
                     AND conversation_id <> ''
                     AND rowid < (
                         SELECT rowid FROM tool_approval_requests WHERE id = ?
                     )""",
                (approval_id, approval_id),
            )
            row = connection.execute(
                "SELECT * FROM tool_approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return self._decode(row)

    def claim_continuation(
        self,
        approval_id: str,
        *,
        conversation_id: str,
        request_id: str,
    ) -> dict | None:
        """Lie une seule continuation agentique à une approbation exécutée.

        Le même ``request_id`` peut rejouer la lecture du flux durable après une
        coupure réseau, mais un autre tour ne peut pas réutiliser l'approbation.
        """
        marker = f"continued:{request_id}"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE tool_approval_requests
                   SET decision_reason = ?
                   WHERE id = ? AND conversation_id = ?
                     AND status = 'approved'
                     AND decision_reason = 'executed'""",
                (marker, approval_id, conversation_id),
            )
            row = connection.execute(
                "SELECT * FROM tool_approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        result = self._decode(row)
        if (
            result is None
            or result.get("conversation_id") != conversation_id
            or result.get("status") != "approved"
            or result.get("decision_reason") != marker
        ):
            return None
        return result


repository = ToolApprovalRepository()
create_or_reuse = repository.create_or_reuse
get = repository.get
resolve_status = repository.resolve_status
claim = repository.claim
finish = repository.finish
deny = repository.deny
claim_continuation = repository.claim_continuation
