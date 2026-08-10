"""Tests de séparation et chiffrement du corpus d'usage réel."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from real_usage_corpus import publish_private_extraction


def _xor(value: bytes, purpose: str) -> bytes:
    key = hashlib.sha256(purpose.encode("ascii")).digest()
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(value))


def _fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE messages (
          id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT,
          tool_calls TEXT, tool_results TEXT, created_at TEXT
        );
        CREATE TABLE tool_executions (
          id TEXT PRIMARY KEY, tool_name TEXT, args TEXT, result TEXT, success INTEGER,
          duration_ms INTEGER, created_at TEXT, conversation_id TEXT, request_id TEXT
        );
        INSERT INTO conversations VALUES ('real', 'Réelle', '2026-01-01', '2026-01-01');
        INSERT INTO messages VALUES ('m1','real','user','trouve rapport.pdf',NULL,NULL,'2026-01-01 10:00:00');
        INSERT INTO tool_executions VALUES ('e1','file_find','{}','{}',1,1,'2026-01-01 10:00:01','real','r1');
        INSERT INTO tool_executions VALUES ('e2','pc_file_search','{}','{}',0,1,'2026-01-01 10:00:02','deleted','r2');
        """
    )
    connection.commit()
    connection.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        database = root / "fixture.db"
        _fixture(database)
        manifest_path = root / "manifest.json"
        manifest = publish_private_extraction(
            database_path=database,
            private_directory=root / "private",
            public_manifest_path=manifest_path,
            protect=_xor,
            unprotect=_xor,
        )
        public = manifest_path.read_text(encoding="utf-8")
        text_cipher = (root / "private" / "real-usage-text.dpapi.json").read_text(encoding="utf-8")
        provenance_cipher = (root / "private" / "real-usage-provenance.dpapi.json").read_text(encoding="utf-8")
        assert manifest["message_count"] == 1
        assert manifest["conversation_count"] == 1
        assert "rapport.pdf" not in public
        assert "file_find" not in public
        assert "rapport.pdf" not in text_cipher
        assert "file_find" not in text_cipher
        assert "file_find" not in provenance_cipher
        assert json.loads(public)["labeling_authorized"] is False
    print("Real Usage Corpus OK - DPAPI injectable, séparation texte/provenance et publication sans contenu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
