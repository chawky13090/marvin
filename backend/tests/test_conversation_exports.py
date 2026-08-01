from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import conversation_exports as exports
from email_attachments import validate_attachments


class ConversationExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patches = [
            patch.object(exports.db, "get_conversation", return_value={"id": "cid", "title": "Test export"}),
            patch.object(exports.db, "get_messages_by_conversation", return_value=[
                {"id": "m1", "role": "user", "content": "Bonjour", "created_at": "2026-08-01", "tool_calls": None, "tool_results": None},
                {"id": "m2", "role": "assistant", "content": "authorization: secret-value", "created_at": "2026-08-01", "tool_calls": [{"args": {"access_token": "secret"}}], "tool_results": None},
            ]),
            patch.object(exports, "roots", return_value=(self.root / "machine", self.root / "exports")),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def test_all_formats_are_non_empty_and_valid(self):
        for file_format in ("md", "json", "docx", "pdf"):
            result = exports.export_conversation("cid", file_format, "technique")
            path = Path(result["path"])
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["sha256"])
            if file_format == "json":
                self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["schema"].endswith("v1"))
            elif file_format == "docx":
                with zipfile.ZipFile(path) as archive:
                    self.assertIn("word/document.xml", archive.namelist())
            elif file_format == "pdf":
                self.assertTrue(path.read_bytes().startswith(b"%PDF"))

    def test_transcript_redacts_secrets(self):
        serialized = json.dumps(exports.transcript("cid", "technique"))
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn('"secret"', serialized)

    def test_attachment_rejects_external_path(self):
        path = self.root / "outside.pdf"
        path.write_bytes(b"%PDF")
        with patch("email_attachments.roots", return_value=(self.root / "machine", self.root / "exports")):
            with self.assertRaisesRegex(ValueError, "exports Marvin"):
                validate_attachments([str(path)])

    def test_attachment_hash_prevents_tampering(self):
        export_root = self.root / "exports"
        path = export_root / "documents" / "conversation.pdf"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"%PDF-test")
        with patch("email_attachments.roots", return_value=(self.root / "machine", export_root)):
            with self.assertRaisesRegex(ValueError, "a change"):
                validate_attachments([{"path": str(path), "sha256": "0" * 64}])


if __name__ == "__main__":
    unittest.main()
